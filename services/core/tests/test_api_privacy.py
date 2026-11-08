"""API security (token, origin) and the privacy NFR: zero outbound network by default."""

import socket

import pytest
from fastapi.testclient import TestClient

from folio_core.api.app import create_app
from folio_core.domain.errors import PrivacyBlocked
from folio_core.providers.llm.openai_compat import OpenAICompatibleLLM
from folio_core.providers.privacy import ensure_allowed

from .conftest import drain

TOKEN = "test-token"


@pytest.fixture
def client(container):
    app = create_app(container, TOKEN, start_background=False)
    with TestClient(app) as tc:
        tc.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield tc


def test_token_and_origin_are_enforced(container):
    app = create_app(container, TOKEN, start_background=False)
    with TestClient(app) as tc:
        assert tc.get("/api/health").status_code == 200  # readiness probe is open
        assert tc.get("/api/status").status_code == 401
        assert tc.get("/api/status", params={"token": TOKEN}).status_code == 200
        bad = tc.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://evil.example"})
        assert bad.status_code == 403
        ok = tc.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}", "Origin": "tauri://localhost"})
        assert ok.status_code == 200


def test_full_loop_over_http(client, container, files):
    r = client.post("/api/roots", json={"path": str(files / "contract.pdf")})
    assert r.status_code == 200, r.text
    drain(container)
    src = client.get("/api/sources").json()[0]
    assert src["status"] == "indexed"
    assert client.get(f"/api/sources/{src['id']}/file").content.startswith(b"%PDF")

    label = client.post("/api/labels", json={"transcript": "This PDF is the Acme contract",
                                             "target_kind": "source", "target_ids": [src["id"]]}).json()
    assert label["parsed"]["preview"] == ["“Acme contract” (Contract, new) is this file"]
    assert client.post(f"/api/labels/{label['id']}/confirm").json()["status"] == "committed"

    found = client.get("/api/search", params={"q": "Acme contract"}).json()
    acme = next(e for e in found["entities"] if e["type"] == "Contract")
    card = client.get(f"/api/entities/{acme['id']}").json()
    assert card["files"][0]["id"] == src["id"]
    assert client.get("/api/views/graph").status_code == 200
    assert client.get("/api/review").status_code == 200
    assert client.post("/api/undo", json={}).status_code == 200
    assert client.get("/api/export/markdown").status_code == 200
    status = client.get("/api/status").json()
    assert status["network_mode"] == "local" and all(p["local"] for p in status["providers"])


def test_errors_map_to_http_status(client):
    assert client.get("/api/entities/ent_missing").status_code == 404
    assert client.post("/api/entities", json={"type": "Spaceship", "name": "X"}).status_code == 200  # open schema
    r = client.post("/api/entities", json={"type": "Person", "name": "  "})
    assert r.status_code == 422


def test_zero_outbound_network_in_default_mode(container, files, monkeypatch):
    """NFR privacy: the whole loop runs without any non-loopback connection."""
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
            raise AssertionError(f"outbound connection attempted to {address}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    container.ingestion.add_root(str(files))
    drain(container)
    src = container.ingestion.roots()[0]
    assert src
    label = container.labels.preview("this is a contract", "entity",
                                     [container.knowledge.create_entity("Document", "x").id])
    container.labels.confirm(label.id)
    assert container.search.search("Acme")
    assert not container.queue.list("failed")


def test_cloud_provider_requires_opt_in(container):
    cloud = OpenAICompatibleLLM("https://api.example.com/v1", "big-model")
    assert not cloud.is_local
    with pytest.raises(PrivacyBlocked):
        ensure_allowed(container.kdb, cloud)
    with container.ledger.group("user", "settings.cloud") as tx:
        tx.upsert("settings", {"id": "cloud.enabled", "value": True})
    ensure_allowed(container.kdb, cloud)  # no exception once the project opts in
