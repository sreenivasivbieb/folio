"""Regression tests for the backend audit: each test names the finding it guards."""

import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from folio_core.api.app import create_app
from folio_core.domain.errors import InvalidInput
from folio_core.organize.drops import DropPlan, normalize_plan
from folio_core.providers.llm.fake import FakeLLM
from folio_core.providers.llm.openai_compat import OpenAICompatibleLLM
from folio_core.providers.llm.router import key_name
from folio_core.store import repo

from .conftest import drain, make_container
from .test_drops import LABEL, _Model, _project

TOKEN = "t" * 32


def _labelled(c, tmp_path, name, label=LABEL):
    drop = c.drops.create([str(_project(tmp_path / name))], "copy")
    drain(c)
    c.drops.set_label(drop["id"], label)
    drain(c)
    return c.drops.get(drop["id"])


def test_relabeling_one_drop_keeps_a_shared_projects_facts(container, tmp_path):  # 1
    a = _labelled(container, tmp_path, "a")
    b = _labelled(container, tmp_path, "b")
    project = a["project"]["id"]
    before = container.kdb["claims"].count_documents({"subject_id": project})
    container.drops.set_label(b["id"], "Totally different thing for the Moon project")
    drain(container)
    assert container.drops.get(a["id"])["project"]["id"] == project
    assert container.kdb["claims"].count_documents({"subject_id": project}) == before


def test_ai_claims_cite_the_files_and_are_forgotten_with_them(container, tmp_path):  # 2
    container.drops.llm = _Model({"project_name": "Pune Solar", "virtual_folders": [], "tags": ["Solar"]})
    drop = _labelled(container, tmp_path, "p")
    model_claims = [d for d in container.kdb["claims"].find() if d["extractor"]["kind"] == "model"]
    assert model_claims and all(d.get("evidence") for d in model_claims)
    out = container.ingestion.forget_source(drop["files"][0]["source_id"])
    assert out["evidence_removed"] > 0 and out["claims_flagged"] == 0


@pytest.mark.parametrize("q", ["**", "!!", "%%"])
def test_punctuation_only_search_does_not_fail(container, tmp_path, q):  # 3
    f = tmp_path / "n.txt"
    f.write_text("hello world")
    container.vault.import_paths([str(f)], "copy")
    drain(container)
    container.search.search(q)


def test_topic_reaches_files_in_project_folders(container, tmp_path):  # 4
    container.drops.llm = _Model({"project_name": "P", "tags": ["Solar"], "virtual_folders": [
        {"folder": "F", "files": ["pune-solar/docs/architecture.md"]}]})
    _labelled(container, tmp_path, "p")
    topic = next(e for e in repo.search_entities(container.kdb, "Solar") if e.type == "Topic")
    assert len(repo.files_tagged(container.kdb, topic.id)) == 4
    assert "Solar" in [t["name"] for t in repo.top_tags(container.kdb)]


def test_merging_extra_folders_loses_no_file():  # 5
    files = [f"p/f{i}.txt" for i in range(16)] + ["p/other.txt"]
    plan = DropPlan(project_name="P", virtual_folders=[
        {"folder": f"G{i}", "files": files[2 * i:2 * i + 2]} for i in range(8)])
    out = normalize_plan(plan, files)
    assert sorted(f for g in out.virtual_folders for f in g.files) == sorted(files)


def test_undo_after_rename_removes_the_entity(container):  # 7
    e = container.knowledge.create_entity("Person", "Priya")
    container.knowledge.update_entity(e.id, name="Priya Sharma")
    container.ledger.undo()
    container.ledger.undo()
    assert repo.get_entity(container.kdb, e.id) is None


def test_label_dates_are_valid_from(container, tmp_path):  # 8
    _labelled(container, tmp_path, "p", LABEL + " on 2024-01-15")
    dates = list(container.kdb["claims"].find({"predicate": "date"}))
    assert dates and all(d.get("valid_from") == d["value"] for d in dates if len(d["value"]) == 10)


def test_index_reset_keeps_vector_search_working(container, tmp_path):  # 12
    container.index.reset()
    f = tmp_path / "r.txt"
    f.write_text("after reset text")
    container.vault.import_paths([str(f)], "copy")
    drain(container)
    assert container.queue.list("failed") == []


def test_export_without_origin_needs_a_folder(container, tmp_path):  # 14
    f = tmp_path / "e.txt"
    f.write_text("export me")
    container.vault.import_paths([str(f)], "move")
    drain(container)
    sid = repo.list_sources(container.kdb)[0].id
    container.kdb["sources"].update_one({"_id": sid}, {"$set": {"origin_path": None}})
    with pytest.raises(InvalidInput, match="choose a folder"):
        container.vault.export(sid, None, "copy")


def test_trashing_a_missing_file_keeps_its_path(container, tmp_path):  # 15
    f = tmp_path / "t.txt"
    f.write_text("trash me")
    container.vault.import_paths([str(f)], "copy")
    drain(container)
    src = repo.list_sources(container.kdb)[0]
    shutil.rmtree(Path(src.path).parent)
    container.vault.trash(src.id)
    assert repo.get_source(container.kdb, src.id).path == src.path


def test_fake_llm_is_unconfigured_by_default():  # 16
    assert FakeLLM().configured is False and FakeLLM(configured=True).configured is True


def test_drop_reports_import_stats(container, tmp_path):  # 19
    drop = container.drops.create([str(_project(tmp_path / "p"))], "copy")
    drain(container)
    stats = container.drops.get(drop["id"])["import_stats"]
    assert stats == {"imported": 4, "duplicates": 0, "failed": 0, "skipped": 3}


def test_model_list_may_be_a_bare_array():  # 21
    llm = OpenAICompatibleLLM("http://127.0.0.1:1/v1", "m", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=[{"id": "a"}])))
    assert llm.list_models() == ["a"]


def test_interrupted_jobs_do_not_burn_an_attempt(container):  # 23
    job_id = container.queue.enqueue("nope", {})
    container.queue.claim()
    container.queue.recover()
    assert container.queue.get(job_id).attempts == 0


def test_job_without_handler_fails_at_once(container):  # 27
    job_id = container.queue.enqueue("no_such_kind", {}, max_attempts=5)
    drain(container)
    job = container.queue.get(job_id)
    assert job.status == "failed" and job.attempts == 1


def test_untracked_import_leaves_no_orphan(container, tmp_path, monkeypatch):  # 24
    f = tmp_path / "o.txt"
    f.write_text("orphan?")

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(container.ingestion, "_track", boom)
    stats = container.vault.import_paths([str(f)], "move")
    assert stats["failed"] == 1 and f.exists()
    assert not any(p.is_file() for p in container.vault.dir.rglob("*"))


def test_rejected_llm_settings_keep_the_saved_key(tmp_path):  # 10
    c = make_container(tmp_path, llm=None)
    body = {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "m"}
    with TestClient(create_app(c, TOKEN, start_background=False)) as tc:
        tc.headers["Authorization"] = f"Bearer {TOKEN}"
        assert tc.put("/api/llm", json={**body, "api_key": "sk-or-1234567890abcd"}).status_code == 200
        assert tc.put("/api/llm", json={**body, "api_key": ""}).status_code == 422
        assert c.llm.configured  # the bad request changed nothing
        c.secrets.set(key_name("openrouter"), None)
        assert not c.llm.configured  # a hosted provider without a key is not usable
