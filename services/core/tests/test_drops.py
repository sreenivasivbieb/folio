"""Drop -> label -> organize: intake, offline rules, AI plan, graph, search, disk organization."""

import json
from pathlib import Path

import pytest

from folio_core.organize.drops import DropPlan, normalize_plan, rule_plan
from folio_core.store import repo

from .conftest import drain

LABEL = "Final architecture docs, datasets, and meeting notes with Rahul for the Pune Solar project"


def _project(tmp_path):
    root = tmp_path / "pune-solar"
    files = {"docs/architecture.md": "# Inverter layout\nString inverters on the east roof.",
             "docs/site-survey.md": "Roof survey, March 2026.",
             "data/readings.csv.txt": "kwh,day\n12,1\n",
             "meetings/2026-03-02.txt": "Rahul: procurement of panels approved.",
             "node_modules/x/index.js": "junk", ".git/config": "junk", "build/out.txt": "junk"}
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return root


class _Model:
    configured, is_local, model_id = True, True, "test:model"

    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def complete_json(self, system, user, schema):
        self.prompts.append(user)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


def _drop(container, tmp_path, mode="copy"):
    drop = container.drops.create([str(_project(tmp_path))], mode)
    assert drop["status"] == "importing" and drop["file_count"] == 4 and drop["skipped"] == 3
    drain(container)
    drop = container.drops.get(drop["id"])
    assert drop["status"] == "imported" and len(drop["files"]) == 4
    return drop


def test_label_organizes_offline_with_rules(container, tmp_path):
    drop = _drop(container, tmp_path)
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    drop = container.drops.get(drop["id"])
    assert drop["status"] == "organized" and drop["engine"] == "rules"
    assert drop["project"]["name"] == "Pune Solar Project"
    folders = {f["name"]: f["folder"] for f in drop["files"]}
    assert folders == {"architecture.md": "Docs", "site-survey.md": "Docs", "readings.csv.txt": "Data",
                       "2026-03-02.txt": "Meetings"}
    assert {e["name"] for e in drop["plan"]["entities"]} == {"Rahul"}


def test_graph_has_project_folders_files_and_people(container, tmp_path):
    drop = _drop(container, tmp_path)
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    g = container.views.graph(include_mentions=True)
    types = {n["name"]: n["type"] for n in g["nodes"]}
    assert types["Pune Solar Project"] == "Project" and types["Rahul"] == "Person"
    assert types["Docs"] == "Folder" and types["architecture.md"] == "Document"
    by_id = {n["id"]: n["name"] for n in g["nodes"]}
    edges = {(by_id[e["source"]], e["predicate"], by_id[e["target"]]) for e in g["edges"]}
    assert ("Docs", "part_of", "Pune Solar Project") in edges
    assert ("architecture.md", "part_of", "Docs") in edges
    assert ("Pune Solar Project", "involves", "Rahul") in edges


def test_ai_plan_is_used_and_label_comes_first(container, tmp_path):
    drop = _drop(container, tmp_path)
    plan = {"project_name": "Pune Solar Rooftop", "summary": "Design and data for a rooftop plant.",
            "virtual_folders": [{"folder": "Design", "files": ["pune-solar/docs/architecture.md", "pune-solar/docs/site-survey.md"]},
                                {"folder": "Measurements", "files": ["pune-solar/data/readings.csv.txt"]}],
            "tags": ["Solar energy"], "entities": [{"name": "Rahul", "type": "Person"}],
            "graph_edges": [{"source": "Rahul", "relation": "reviewed", "target": "Design"}]}
    model = _Model(plan)
    container.drops.llm = model
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    assert model.prompts[0].startswith(f"USER LABEL: {LABEL}")
    drop = container.drops.get(drop["id"])
    assert drop["engine"] == "test:model" and drop["project"]["name"] == "Pune Solar Rooftop"
    folders = {f["name"]: f["folder"] for f in drop["files"]}
    assert folders["2026-03-02.txt"] == "Other"  # every file lands in exactly one folder
    tags = {t["name"] for t in repo.top_tags(container.kdb)}
    assert {"Pune Solar Rooftop", "Design"} <= tags


@pytest.mark.parametrize("answer", ["not json", RuntimeError("rate limited")])
def test_bad_or_unreachable_model_falls_back_to_rules(container, tmp_path, answer):
    drop = _drop(container, tmp_path)
    container.drops.llm = _Model(answer)
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    drop = container.drops.get(drop["id"])
    assert drop["status"] == "organized" and drop["engine"] == "rules"


def test_relabeling_replaces_the_previous_organization(container, tmp_path):
    drop = _drop(container, tmp_path)
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    container.drops.set_label(drop["id"], "Thesis material for the Green Campus project")
    drain(container)
    names = {n["name"] for n in container.views.graph()["nodes"]}
    assert "Green Campus Project" in names and "Pune Solar Project" not in names and "Rahul" not in names


def test_search_finds_files_by_project_and_label(container, tmp_path):
    drop = _drop(container, tmp_path)
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    ents = repo.search_entities(container.kdb, "Pune Solar")
    assert len(container.search.files("Pune Solar", ents)) == 4
    assert [p.name for p in container.search.projects_matching("meeting notes rahul")] == ["Pune Solar Project"]
    by_label = container.search.files("datasets meeting", [])
    assert len(by_label) == 4 and by_label[0]["via"].startswith("label:")


def test_disk_organization_preview_apply_undo(container, tmp_path):
    drop = _drop(container, tmp_path)
    container.drops.llm = _Model({"project_name": "Solar", "virtual_folders": [
        {"folder": "Design", "files": ["pune-solar/docs/architecture.md"]},
        {"folder": "Notes", "files": ["pune-solar/meetings/2026-03-02.txt"]}]})
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    root = tmp_path / "pune-solar"
    preview = container.drops.disk_preview(drop["id"])
    targets = {Path(m["to"]).relative_to(root).as_posix() for m in preview["moves"]}
    assert {"Design/architecture.md", "Notes/2026-03-02.txt", "Other/readings.csv.txt"} <= targets
    assert (root / "docs" / "architecture.md").exists()  # preview moves nothing
    container.drops.disk_apply(drop["id"])
    assert (root / "Design" / "architecture.md").exists() and not (root / "docs" / "architecture.md").exists()
    assert not (root / "meetings").exists()  # emptied by the moves: removed
    assert (root / "node_modules").exists()
    assert (root / "node_modules" / "x" / "index.js").exists()  # junk is never touched
    undo = container.drops.disk_undo(drop["id"])
    assert undo["left"] == 0 and (root / "docs" / "architecture.md").exists() and not (root / "Design").exists()


def test_moved_drops_cannot_be_organized_on_disk(container, tmp_path):
    from folio_core.domain.errors import InvalidInput

    drop = _drop(container, tmp_path, mode="move")
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    with pytest.raises(InvalidInput):
        container.drops.disk_preview(drop["id"])


def test_drop_api_round_trip(container, tmp_path):
    from fastapi.testclient import TestClient

    from folio_core.api.app import create_app

    client = TestClient(create_app(container, "t", start_background=False))
    h = {"Authorization": "Bearer t"}
    r = client.post("/api/drops", json={"paths": [str(_project(tmp_path))], "mode": "copy"}, headers=h)
    assert r.status_code == 200 and r.json()["skipped"] == 3
    drain(container)
    drop_id = r.json()["id"]
    r = client.post(f"/api/drops/{drop_id}/label", json={"label_text": LABEL}, headers=h)
    assert r.status_code == 200
    drain(container)
    body = client.get(f"/api/drops/{drop_id}", headers=h).json()
    assert body["status"] == "organized" and body["project"]["name"] == "Pune Solar Project"
    assert client.post(f"/api/drops/{drop_id}/disk-organization/preview", headers=h).status_code == 200


def test_plan_normalization_caps_and_assigns_everything():
    files = [f"p/f{i}.txt" for i in range(12)]
    plan = DropPlan(project_name="  P  ", virtual_folders=[{"folder": f"G{i}", "files": [files[i]]} for i in range(10)],
                    tags=["a", "Solar", "x" * 80, "Solar", "Grid", "PV", "Roof", "Extra"])
    out = normalize_plan(plan, files)
    assert out.project_name == "P" and len(out.virtual_folders) <= 8
    assert sorted(f for g in out.virtual_folders for f in g.files) == sorted(files)
    assert out.tags == ["Solar", "Grid", "PV", "Roof", "Extra"]


def test_rules_read_people_dates_and_project_names():
    plan = rule_plan("Budget sheets with Priya and Arjun for the Atlas project, due 2026-04-15",
                     [{"rel_path": "budget.xlsx", "kind": "other"}], ["/x/budget.xlsx"])
    assert plan.project_name == "Atlas Project"
    assert {(e.name, e.type) for e in plan.entities} == {("Priya", "Person"), ("Arjun", "Person"), ("2026-04-15", "Date")}
    assert plan.virtual_folders[0].folder == "Data"


def test_plan_drops_duplicate_entities_and_membership_edges():
    files = ["p/docs/a.md", "p/meet/b.txt"]
    plan = DropPlan(project_name="Pune Solar Project", tags=["Solar"],
                    virtual_folders=[{"folder": "Docs", "files": ["p/docs/a.md"]}, {"folder": "Meetings", "files": ["p/meet/b.txt"]}],
                    entities=[{"name": "Pune Solar Project", "type": "Topic"}, {"name": "Solar", "type": "Topic"},
                              {"name": "Rahul", "type": "Person"}, {"name": "rahul", "type": "Person"}],
                    graph_edges=[{"source": "Pune Solar Project", "relation": "contains", "target": "Docs"},
                                 {"source": "Docs", "relation": "contains", "target": "p/docs/a.md"},
                                 {"source": "p/meet/b.txt", "relation": "mentions", "target": "Rahul"}])
    out = normalize_plan(plan, files)
    assert [e.name for e in out.entities] == ["Rahul"]
    assert [(e.source, e.relation, e.target) for e in out.graph_edges] == [("p/meet/b.txt", "mentions", "Rahul")]


def test_tags_never_repeat_the_project_or_a_folder():
    plan = DropPlan(project_name="Solar", tags=["Architecture", "solar", "Energy"],
                    virtual_folders=[{"folder": "Architecture", "files": ["p/a.md"]}])
    assert normalize_plan(plan, ["p/a.md"]).tags == ["Energy"]


def test_drop_files_get_titles_but_no_extra_per_file_tags(container, tmp_path):
    import json as _json

    from folio_core.organize import FileOrganizer

    drop = _drop(container, tmp_path)
    sid = drop["files"][0]["source_id"]
    model = type("M", (), {"configured": True, "is_local": True, "model_id": "m",
                           "complete_json": lambda self, *a: _json.dumps({"title": "Inverter layout",
                                                                          "description": "d", "tags": [{"name": "Noise"}]})})()
    FileOrganizer(kdb=container.kdb, index=container.index, ledger=container.ledger,
                  knowledge=container.knowledge, llm=model).organize(sid)
    org = repo.file_organization(container.kdb, [sid])[sid]
    assert org["title"] == "Inverter layout" and org["tags"] == []


def test_deep_extraction_is_opt_in(tmp_path):
    from .conftest import make_container

    c = make_container(tmp_path)
    c.settings = type(c.settings)(**{**c.settings.__dict__, "auto_extract": False})
    c.ingestion.settings = c.settings
    f = tmp_path / "n.txt"
    f.write_text("Priya Sharma works at Acme Corp.")
    c.vault.import_paths([str(f)], "copy")
    drain(c)
    assert not [j for j in c.queue.list() if j.kind == "extract_source"]


def test_people_named_in_the_label_survive_a_terse_model(container, tmp_path):
    drop = _drop(container, tmp_path)
    container.drops.llm = _Model({"project_name": "Pune Solar Project", "summary": "s", "tags": [], "entities": []})
    container.drops.set_label(drop["id"], LABEL)
    drain(container)
    plan = container.drops.get(drop["id"])["plan"]
    assert {(e["name"], e["type"]) for e in plan["entities"]} == {("Rahul", "Person")}
    assert plan["tags"]  # label keywords when the model gave none
