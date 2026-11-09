"""Regression tests for reviewed logic errors (search DTO, find kwargs, merges, Retry-After, scans)."""

import os
import sys
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from folio_core.providers.llm.openai_compat import retry_after
from folio_core.store import repo

from .conftest import drain


def test_find_honours_limit_skip_and_sort(container):
    col = container.kdb["scratch"]
    col.insert_many([{"_id": f"d{i}", "n": i} for i in range(10)])
    assert len(list(col.find({}, limit=3))) == 3
    assert [d["n"] for d in col.find({}, sort=[("n", -1)], skip=1, limit=2)] == [8, 7]


def test_tx_find_limit_reaches_storage(container):
    for i in range(5):
        container.knowledge.create_entity("Topic", f"topic {i}")
    with container.ledger.group("system", "t") as tx:
        assert len(tx.find("entities", {}, limit=1)) == 1


@pytest.mark.parametrize(("spoken", "kept"), [
    ("merge Alpha Co and Beta Co", "Alpha Co"),
    ("merge Alpha Co with Beta Co", "Alpha Co"),
    ("merge Alpha Co into Beta Co", "Beta Co"),
])
def test_spoken_merge_keeps_the_right_entity(container, spoken, kept):
    a = container.knowledge.create_entity("Organization", "Alpha Co")
    b = container.knowledge.create_entity("Organization", "Beta Co")
    label = container.labels.preview(spoken, "none", [])
    container.labels.confirm(label.id)
    alive = {e.name for e in repo.search_entities(container.kdb, "", ["Organization"])}
    assert alive == {kept}
    assert {a.id, b.id}  # both existed


def test_retry_after_accepts_seconds_and_http_dates():
    assert retry_after("7", 1.0) == 7.0
    assert retry_after(None, 2.0) == 2.0
    assert retry_after("garbage", 3.0) == 3.0
    soon = format_datetime(datetime.now(UTC) + timedelta(seconds=20), usegmt=True)
    assert 15 <= retry_after(soon, 1.0) <= 21
    assert retry_after("Wed, 21 Oct 2015 07:28:00 GMT", 1.0) == 0.0  # in the past


def test_search_files_never_returns_a_null_reason(container, files):
    container.ingestion.add_root(str(files / "contract.pdf"))
    drain(container)
    src = repo.list_sources(container.kdb)[0]
    container.labels.confirm(container.labels.preview("tag this as finance", "source", [src.id]).id)
    ents = repo.search_entities(container.kdb, "finance")
    ents[0].name = ""  # an entity with an empty name must not break the response model
    from folio_core.api.dto import FileHit

    hits = container.search.files("finance", ents)
    assert hits and all(FileHit(**h).via for h in hits)


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions, non-root")
def test_deleted_files_are_marked_missing_despite_an_unreadable_folder(container, tmp_path):
    root = tmp_path / "docs"
    (root / "locked").mkdir(parents=True)
    (root / "gone.txt").write_text("soon deleted")
    (root / "locked" / "secret.txt").write_text("hidden")
    container.ingestion.add_root(str(root))
    drain(container)
    (root / "gone.txt").unlink()
    (root / "locked").chmod(0)
    try:
        container.ingestion.rescan_all()
        drain(container)
        by_name = {os.path.basename(s.path): s.status.value for s in repo.list_sources(container.kdb)}
        assert by_name["gone.txt"] == "missing"
        assert by_name["secret.txt"] != "missing"  # could not look there: not assumed deleted
    finally:
        (root / "locked").chmod(0o700)


def test_large_documents_do_not_hit_the_sql_parameter_limit(container):
    import sqlite3

    conn = container.index.reader()
    limit = conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)  # an older SQLite build
    try:
        many = list(range(1, 5000))
        assert container.ingestion._existing_vectors(many, [str(i) for i in many]) == {}
    finally:
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, limit)
    with container.index.write() as w:
        w.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        container.vectors.remove(w, list(range(1, 5000)))  # batched: no "too many SQL variables"


def test_new_databases_reclaim_space_incrementally(container):
    for conn in (container.kdb._writer, container.index._writer):
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    container.kdb.compact()
    container.index.compact()


def test_old_bloated_database_is_compacted_once(tmp_path):
    import sqlite3
    import threading

    from folio_core.store.maintenance import compact

    path = tmp_path / "old.db"
    c = sqlite3.connect(path, isolation_level=None)
    c.execute("create table t(x)")
    c.executemany("insert into t values (?)", [("x" * 2000,)] * 6000)
    c.execute("delete from t")
    before = path.stat().st_size
    compact(c, threading.RLock(), "old.db")
    assert c.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    assert path.stat().st_size < before / 4


def test_microphone_failure_never_leaves_recording_stuck(tmp_path):
    from folio_core.speech.recorder import MicRecorder

    class Broken:
        def stop(self):
            raise OSError("device unplugged")

        def close(self):
            raise OSError("device gone")

    rec = MicRecorder()
    rec._stream, rec._frames, rec._rate = Broken(), [b"\x00\x00" * 1600], 16000
    rec.stop(tmp_path / "a.wav")
    assert not rec.recording


def test_watch_limit_does_not_break_adding_a_folder(container, files, monkeypatch):
    import errno

    w = container.watcher
    w.start()
    try:
        def full(*a, **k):
            raise OSError(errno.ENOSPC, "inotify watch limit reached")

        monkeypatch.setattr(w._observer, "schedule", full)
        container.ingestion.add_root(str(files), watch=True)
        w.sync()  # logs a warning instead of raising
    finally:
        w.stop()


def test_large_drive_backup_uses_a_resumable_upload(tmp_path):
    import httpx

    from folio_core.providers.drive import MULTIPART_LIMIT, DriveService
    from folio_core.providers.secrets import SecretStore

    seen = []

    def google(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.params.get("uploadType"), len(request.content)))
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
        if request.method == "POST":
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/session/1"})
        return httpx.Response(200, json={"id": "big"})

    store = SecretStore(tmp_path / "secrets.json")
    for k, v in {"drive.client_id": "c", "drive.client_secret": "s", "drive.refresh_token": "r"}.items():
        store.set(k, v)
    drive = DriveService(store)
    drive.client = httpx.Client(transport=httpx.MockTransport(google))
    assert drive.backup({"blob": "x" * (MULTIPART_LIMIT + 10)})["id"] == "big"
    assert [s[:2] for s in seen[1:]] == [("POST", "resumable"), ("PUT", None)]
    assert seen[-1][2] > MULTIPART_LIMIT
