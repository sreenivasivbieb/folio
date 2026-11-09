"""Search should forgive the user: partial words, typos, descriptions, and a useful empty state."""

from pathlib import Path

from folio_core.store import repo

from .conftest import drain


def _add(c, tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text)
    c.vault.import_paths([str(f)], "copy")
    drain(c)
    return next(s for s in repo.list_sources(c.kdb) if Path(s.path).name == name)


def test_partial_words_find_passages(container, tmp_path):
    _add(container, tmp_path, "notes.md", "Our hackathon demo went well.")
    assert container.search.search("hack")


def test_typos_find_entities_and_files(container, tmp_path):
    container.knowledge.create_entity("Event", "Lexsi Hackathon")
    assert [e.name for e in repo.search_entities(container.kdb, "lexsi hackthon")] == ["Lexsi Hackathon"]
    _add(container, tmp_path, "quarterly-budget.txt", "numbers")
    assert [Path(f["path"]).name for f in container.search.files("budjet", [])] == ["quarterly-budget.txt"]


def test_file_names_match_words_in_any_order(container, tmp_path):
    _add(container, tmp_path, "demo_video_lexsi.txt", "x")
    assert container.search.files("lexsi demo", [])


def test_descriptions_from_labels_find_the_file(container, tmp_path):
    src = _add(container, tmp_path, "screenrecording.txt", "nothing useful inside")
    container.labels.confirm(container.labels.preview("lexsi hackathon video demo", "source", [src.id]).id)
    hits = container.search.files("hackathon video", [])
    assert [h["source_id"] for h in hits] == [src.id]


def test_empty_query_suggests_recent_files_and_entities(container, tmp_path):
    from fastapi.testclient import TestClient

    from folio_core.api.app import create_app

    _add(container, tmp_path, "recent.txt", "fresh")
    container.knowledge.create_entity("Topic", "kites")
    client = TestClient(create_app(container, "t", start_background=False))
    body = client.get("/api/search", params={"q": ""}, headers={"Authorization": "Bearer t"}).json()
    assert [Path(f["path"]).name for f in body["files"]] == ["recent.txt"]
    assert [e["name"] for e in body["entities"]] == ["kites"]
