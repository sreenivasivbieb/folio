"""Regression tests for destructive failure paths, scanning, and resumable work."""

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from folio_core.api.app import create_app
from folio_core.config import Settings
from folio_core.domain.errors import InvalidInput, Unavailable
from folio_core.domain.models import Extractor, SourceStatus
from folio_core.extraction.types import ExtractionFailed
from folio_core.jobs import JobQueue
from folio_core.realtime import Bus
from folio_core.runtime import instance_lock
from folio_core.store import repo
from folio_core.store.index_db import IndexDB

from .conftest import drain, make_container


def test_failed_extraction_preserves_previous_proposals(container, files):
    container.ingestion.add_root(str(files))
    drain(container)
    claim = container.kdb["claims"].find_one({"status": "proposed", "evidence.source_id": {"$ne": None}})
    assert claim
    source_id = claim["evidence"][0]["source_id"]
    before = list(container.kdb["claims"].find({"evidence.source_id": source_id}))

    class FailingExtractor:
        model_id, prompt_version, uses_llm = "failing-fixture", "v1", False

        def extract(self, text, ctx):
            raise ExtractionFailed("invalid model reply")

    container.extraction.extractor = FailingExtractor
    container.queue.enqueue("extract_source", {"source_id": source_id})
    drain(container)
    assert list(container.kdb["claims"].find({"evidence.source_id": source_id})) == before
    assert container.index.reader().execute("SELECT COUNT(*) FROM extraction_issues").fetchone()[0] > 0


@pytest.mark.parametrize("action", ["forget", "remove"])
def test_inflight_indexing_cannot_restore_removed_file(container, tmp_path, monkeypatch, action):
    path = tmp_path / "note.txt"
    path.write_text("Priya owns Acme Contract.")
    root = container.ingestion.add_root(str(path))
    real_parse = container.ingestion._parse

    def parse_then_remove(file, job):
        units = real_parse(file, job)
        if action == "forget":
            container.ingestion.forget_source(job.payload["source_id"])
        else:
            container.ingestion.remove_root(root.id)
        return units

    monkeypatch.setattr(container.ingestion, "_parse", parse_then_remove)
    drain(container)
    source = repo.source_by_path(container.kdb, str(path))
    assert source.status == (SourceStatus.FORGOTTEN if action == "forget" else SourceStatus.REMOVED)
    assert not repo.chunks_for_source(container.index.reader(), source.id)
    assert container.kdb["claims"].count_documents({"evidence.source_id": source.id}) == 0


def test_invalid_import_changes_nothing(container, files, tmp_path):
    container.ingestion.add_root(str(files))
    drain(container)
    data = deepcopy(container.exporter.to_json())
    data["claims"].append(deepcopy(data["claims"][0]))
    other = make_container(tmp_path / "restore")
    schema_before = list(other.kdb["schema_versions"].find())
    with pytest.raises(InvalidInput, match="duplicate id"):
        other.exporter.from_json(data)
    assert other.kdb["entities"].count_documents({}) == 0
    assert other.kdb["claims"].count_documents({}) == 0
    assert list(other.kdb["schema_versions"].find()) == schema_before


def test_database_conflict_rolls_back_complete_import(container, files, tmp_path):
    container.ingestion.add_root(str(files))
    drain(container)
    data = deepcopy(container.exporter.to_json())
    other = make_container(tmp_path / "restore")
    empty = tmp_path / "empty"
    empty.mkdir()
    other.ingestion.add_root(str(empty))
    data["roots"][0]["path"] = str(empty)
    before = other.exporter.to_json()
    with pytest.raises(InvalidInput, match="nothing was imported"):
        other.exporter.from_json(data)
    after = other.exporter.to_json()
    for coll in ("schema_versions", "settings", "roots", "sources", "entities", "claims", "events", "event_groups"):
        assert after[coll] == before[coll], coll


def test_change_during_running_job_is_not_lost(tmp_path):
    db = IndexDB(tmp_path / "index.db")
    try:
        queue = JobQueue(db, Bus())
        job_id = queue.enqueue("index_source", {"source_id": "s"}, dedupe_key="index:s")
        assert queue.claim().id == job_id
        queue.enqueue("index_source", {"source_id": "s"}, dedupe_key="index:s", priority=10)
        queue.finish(job_id)
        repeated = queue.claim()
        assert repeated.id == job_id and repeated.priority == 10 and repeated.attempts == 1
        queue.finish(job_id)
        assert queue.get(job_id).status == "done" and queue.claim() is None
    finally:
        db.close()


def test_computer_scan_records_metadata_and_respects_exclusions(container, tmp_path):
    folder = tmp_path / "library"
    folder.mkdir()
    (folder / "note.txt").write_text("A document without private data.")
    (folder / "archive.bin").write_bytes(b"\x00\x01")
    hidden = folder / ".notes"
    hidden.mkdir()
    (hidden / "hidden.txt").write_text("An explicitly included hidden note.")
    ignored = folder / "node_modules"
    ignored.mkdir()
    (ignored / "ignored.txt").write_text("Do not index dependency folders.")
    (folder / "loop").symlink_to(folder, target_is_directory=True)
    container.ingestion.add_root(str(folder), include_hidden=True)
    drain(container)
    sources = repo.list_sources(container.kdb)
    assert {Path(s.path).name for s in sources} == {"note.txt", "archive.bin", "hidden.txt"}
    assert next(s for s in sources if s.path.endswith("archive.bin")).status == SourceStatus.METADATA


def test_unreadable_file_does_not_abort_scan(container, tmp_path, monkeypatch):
    folder = tmp_path / "library"
    folder.mkdir()
    for name in ("good.txt", "blocked.txt"):
        (folder / name).write_text("Fixture text.")
    real_track = container.ingestion._track

    def track(path, *args):
        if path.name == "blocked.txt":
            raise PermissionError("fixture permission denied")
        return real_track(path, *args)

    monkeypatch.setattr(container.ingestion, "_track", track)
    container.ingestion.add_root(str(folder))
    drain(container)
    assert [Path(s.path).name for s in repo.list_sources(container.kdb)] == ["good.txt"]


def test_only_one_core_can_own_a_data_folder(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    with instance_lock(settings), pytest.raises(Unavailable, match="already running"), instance_lock(settings):
        pytest.fail("a second core acquired the same data folder")
    with instance_lock(settings):
        pass


def test_table_pages_reach_facts_beyond_first_page(container):
    entity = container.knowledge.create_entity("Topic", "Pagination fixture")
    for value in range(105):
        container.knowledge.add_claim(subject_id=entity.id, predicate="fixture_value", value=value,
                                      extractor=Extractor(kind="user"))
    with TestClient(create_app(container, "fixture", start_background=False)) as client:
        client.headers["Authorization"] = "Bearer fixture"
        url = f"/api/views/table?entity_id={entity.id}&order=-value&limit=100"
        first = client.get(url).json()
        second = client.get(url + "&offset=100").json()
        assert first["has_more"] and not second["has_more"]
        assert len(first["claims"]) == 100 and len(second["claims"]) == 5
        assert first["claims"][0]["value"] == 104 and second["claims"][-1]["value"] == 0
        assert not ({c["id"] for c in first["claims"]} & {c["id"] for c in second["claims"]})


def test_filename_pages_search_metadata_without_losing_results(container, tmp_path):
    folder = tmp_path / "library"
    folder.mkdir()
    for name in ("literal[1].bin", "other.bin", "third.bin"):
        (folder / name).write_bytes(b"fixture")
    container.ingestion.add_root(str(folder), watch=False)
    drain(container)
    with TestClient(create_app(container, "fixture", start_background=False)) as client:
        client.headers["Authorization"] = "Bearer fixture"
        first = client.get("/api/files?limit=1").json()
        second = client.get("/api/files?limit=1&offset=1").json()
        assert first["total"] == 3 and first["sources"][0]["id"] != second["sources"][0]["id"]
        found = client.get("/api/files", params={"q": "literal[1]"}).json()
        assert found["total"] == 1 and found["sources"][0]["status"] == "metadata"


def test_folder_added_inside_a_system_folder_is_still_indexed(container, tmp_path, monkeypatch):
    # Windows lists %TEMP% as a system folder; a folder the user adds there must still be read,
    # while scanning a parent folder keeps skipping it.
    system = tmp_path / "system-temp"
    inside = system / "my-notes"
    inside.mkdir(parents=True)
    (inside / "note.txt").write_text("Fixture text.")
    (tmp_path / "outside.txt").write_text("Fixture text.")
    monkeypatch.setattr("folio_core.ingestion.service.SYSTEM_EXCLUSIONS", [system.resolve()])

    container.ingestion.add_root(str(tmp_path))
    drain(container)
    assert sorted(Path(s.path).name for s in repo.list_sources(container.kdb)) == ["outside.txt"]

    container.ingestion.add_root(str(inside))
    drain(container)
    assert sorted(Path(s.path).name for s in repo.list_sources(container.kdb)) == ["note.txt", "outside.txt"]
