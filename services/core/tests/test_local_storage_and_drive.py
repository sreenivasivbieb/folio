"""Local persistence and user-owned Drive integration, with no live account or network."""

import base64
import hashlib
import json
import threading
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from folio_core.api.app import create_app
from folio_core.domain.errors import InvalidInput
from folio_core.providers.drive import DriveService
from folio_core.providers.secrets import SecretStore
from folio_core.store.local import KnowledgeDB

CLIENT = "fixture-user.apps.googleusercontent.com"
SECRET = "fixture-client-secret"
REFRESH = "fixture-refresh-token"


def test_local_knowledge_reopens_and_rolls_back(tmp_path):
    path = tmp_path / "knowledge.sqlite3"
    store = KnowledgeDB(path)
    store["entities"].insert_one({"_id": "persisted", "name": "Local fixture"})
    with pytest.raises(RuntimeError), store.transaction():
        store["entities"].insert_one({"_id": "rolled_back", "name": "Not committed"})
        store["events"].insert_one({"_id": "event", "seq": 1})
        raise RuntimeError("fixture interruption")
    store.close()
    reopened = KnowledgeDB(path)
    assert reopened["entities"].find_one({"_id": "persisted"})["name"] == "Local fixture"
    assert reopened["entities"].find_one({"_id": "rolled_back"}) is None
    assert reopened["events"].count_documents({}) == 0
    assert path.read_bytes().startswith(b"SQLite format 3")
    reopened.close()


def test_nested_filter_sort_handles_missing_dates(tmp_path):
    store = KnowledgeDB(tmp_path / "knowledge.sqlite3")
    store["claims"].insert_many([
        {"_id": "a", "valid_from": None, "evidence": [{"source_id": "s"}]},
        {"_id": "b", "valid_from": "2026-01-02", "evidence": [{"source_id": "s"}]},
    ])
    rows = list(store["claims"].find({"evidence.source_id": "s"}).sort("valid_from", 1))
    assert [row["_id"] for row in rows] == ["a", "b"]
    store.close()


def test_large_file_id_sets_do_not_hit_sqlite_parameter_limit(tmp_path):
    store = KnowledgeDB(tmp_path / "knowledge.sqlite3")
    store["sources"].insert_one({"_id": "present", "path": "/fixture/present"})
    ids = [f"fixture_{i}" for i in range(40000)] + ["present"]
    assert store["sources"].count_documents({"_id": {"$in": ids}}) == 1
    assert store["sources"].count_documents({"_id": {"$nin": ids}}) == 0
    store.close()


def _google(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/token":
        body = parse_qs(request.content.decode())
        assert body["client_id"] == [CLIENT] and body["client_secret"] == [SECRET]
        if body["grant_type"] == ["authorization_code"]:
            assert body["code_verifier"]
        return httpx.Response(200, json={"access_token": "fixture-access", "refresh_token": REFRESH, "expires_in": 3600})
    assert request.headers["Authorization"] == "Bearer fixture-access"
    if request.method == "POST":
        assert request.url.path == "/upload/drive/v3/files"
        assert b'"format": "folio.v2"' in request.content
        assert SECRET.encode() not in request.content and REFRESH.encode() not in request.content
        return httpx.Response(200, json={"id": "backup_fixture", "name": "folio-backup.json"})
    if request.url.path.endswith("/backup_fixture"):
        if request.url.params.get("alt") == "media":
            return httpx.Response(200, json={"format": "folio.v2", "entities": []})
        return httpx.Response(200, json={"mimeType": "application/json", "appProperties": {"application": "folio"}, "size": "100"})
    return httpx.Response(200, json={"files": [{"id": "backup_fixture", "name": "folio-backup.json"}]})


def test_drive_uses_own_credentials_pkce_and_one_time_state(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return _google(request)

    secrets = SecretStore(tmp_path / "secrets.json")
    drive = DriveService(secrets, transport=httpx.MockTransport(handler))
    authorization = drive.begin(CLIENT, SECRET, "http://127.0.0.1:8765/api/drive/callback")
    query = parse_qs(urlparse(authorization).query)
    assert not requests and query["scope"] == ["https://www.googleapis.com/auth/drive.file"]
    assert query["code_challenge_method"] == ["S256"]
    drive.finish(query["state"][0], "fixture-code")
    token_body = parse_qs(requests[0].content.decode())
    challenge = base64.urlsafe_b64encode(hashlib.sha256(token_body["code_verifier"][0].encode()).digest()).decode().rstrip("=")
    assert query["code_challenge"] == [challenge]
    assert drive.status()["connected"]
    assert SECRET not in json.dumps(drive.status()) and REFRESH not in json.dumps(drive.status())
    with pytest.raises(InvalidInput):
        drive.finish(query["state"][0], "replayed-code")
    assert len(requests) == 1
    drive.backup({"format": "folio.v2", "entities": []})
    assert drive.backups()["files"][0]["id"] == "backup_fixture"
    assert drive.download("backup_fixture")["format"] == "folio.v2"
    drive.disconnect()
    with pytest.raises(InvalidInput, match="Connect"):
        drive.backup({"format": "folio.v2"})
    assert not drive.status()["connected"] and secrets.get("drive.refresh_token") is None
    drive.close()


def test_oauth_callback_is_public_but_state_is_required_and_secrets_are_not_exported(container):
    container.drive.close()
    container.drive = DriveService(container.secrets, transport=httpx.MockTransport(_google))
    with TestClient(create_app(container, "fixture", start_background=False), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/drive/callback?state=invalid&code=invalid").status_code == 400
        assert client.get("/api/drive").status_code == 401
        client.headers["Authorization"] = "Bearer fixture"
        response = client.post("/api/drive/connect", json={"client_id": CLIENT, "client_secret": SECRET})
        assert response.status_code == 200
        state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
        client.headers.pop("Authorization")
        assert client.get("/api/drive/callback", params={"state": state, "code": "fixture-code"}).status_code == 200
        client.headers["Authorization"] = "Bearer fixture"
        assert client.get("/api/drive").json()["connected"]
        exported = json.dumps(container.exporter.to_json())
        assert SECRET not in exported and REFRESH not in exported
        assert "drive.client_secret" not in exported


def test_local_import_keeps_liveness_responsive(container, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_import(data):
        started.set()
        release.wait(5)
        finished.set()
        return {}

    monkeypatch.setattr(container.exporter, "from_json", slow_import)
    with TestClient(create_app(container, "fixture", start_background=False)) as client:
        client.headers["Authorization"] = "Bearer fixture"
        results = []
        worker = threading.Thread(target=lambda: results.append(client.post("/api/import/json", json={"format": "folio.v2"})))
        worker.start()
        try:
            assert started.wait(3)
            assert client.get("/api/health").status_code == 200
            assert not finished.is_set() and worker.is_alive()
        finally:
            release.set()
            worker.join(timeout=5)
        assert results[0].status_code == 200
