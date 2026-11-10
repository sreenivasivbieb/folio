"""The AI organizer: one call per file -> title, description, <=3 broad tags, reusing tags."""

import json
from pathlib import Path

from folio_core.organize import FileOrganizer
from folio_core.store import repo

from .conftest import drain


class _Model:
    configured, is_local, model_id = True, True, "test:model"

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def complete_json(self, system, user, schema):
        self.prompts.append(user)
        return json.dumps(self.answers.pop(0))


def _file(c, tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text)
    c.vault.import_paths([str(f)], "copy")
    drain(c)
    return next(s for s in repo.list_sources(c.kdb) if Path(s.path).name == name)


def _organizer(c, model):
    return FileOrganizer(kdb=c.kdb, index=c.index, ledger=c.ledger, knowledge=c.knowledge, llm=model)


def test_file_gets_title_description_and_few_tags(container, tmp_path):
    src = _file(container, tmp_path, "screenshot-1.txt", "sudo limine-scan ... EFI entries Windows Boot Manager Fedora")
    model = _Model({"title": "Bootloader entries setup", "description": "Adding Windows to the Limine boot menu.",
                    "tags": [{"name": "Linux setup", "type": "Topic"}, {"name": "Limine", "type": "Topic"},
                             {"name": "/boot/efi", "type": "Topic"}, {"name": "Dual boot", "type": "Topic"},
                             {"name": "Extra", "type": "Topic"}]})
    msg = _organizer(container, model).organize(src.id)
    assert msg.startswith("organized")
    org = repo.file_organization(container.kdb, [src.id])[src.id]
    assert org["title"] == "Bootloader entries setup"
    assert org["description"] == "Adding Windows to the Limine boot menu."
    assert [t["name"] for t in org["tags"]] == ["Linux setup", "Limine", "Dual boot"]  # paths dropped, max 3


def test_existing_tags_are_offered_and_reused(container, tmp_path):
    a = _file(container, tmp_path, "a.txt", "first")
    b = _file(container, tmp_path, "b.txt", "second")
    org = _organizer(container, _Model(
        {"title": "A", "description": "a", "tags": [{"name": "Linux setup"}]},
        {"title": "B", "description": "b", "tags": [{"name": "linux Setup"}]}))
    org.organize(a.id)
    org.organize(b.id)
    assert "Linux setup" in org.llm.prompts[1]  # the model is told which tags exist
    tags = repo.top_tags(container.kdb)
    assert [(t["name"], t["count"]) for t in tags] == [("Linux setup", 2)]


def test_reorganizing_replaces_ai_tags_but_keeps_user_labels(container, tmp_path):
    src = _file(container, tmp_path, "notes.txt", "kites")
    container.labels.confirm(container.labels.preview("tag this as hobbies", "source", [src.id]).id)
    org = _organizer(container, _Model({"title": "Kite notes", "description": "x", "tags": [{"name": "Kites"}]},
                                       {"title": "Kite notes", "description": "y", "tags": [{"name": "Outdoors"}]}))
    org.organize(src.id)
    org.organize(src.id)
    names = {t["name"] for t in repo.file_organization(container.kdb, [src.id])[src.id]["tags"]}
    assert names == {"hobbies", "Outdoors"}


def test_extraction_details_are_not_library_tags(container, tmp_path):
    from folio_core.domain.models import Extractor

    src = _file(container, tmp_path, "doc.txt", "x")
    org = _organizer(container, _Model({"title": "T", "description": "d", "tags": [{"name": "Topic A"}]}))
    org.organize(src.id)
    ent = repo.search_entities(container.kdb, "doc.txt")[0]
    other = container.knowledge.create_entity("Tool", "limine-scan")
    container.knowledge.add_claim(subject_id=ent.id, predicate="lists_entry", object_id=other.id,
                                  extractor=Extractor(kind="user"))
    names = {t["name"] for t in repo.file_organization(container.kdb, [src.id])[src.id]["tags"]}
    assert names == {"Topic A"}  # "lists entry" stays a graph fact, not a Library tag


def test_without_a_model_nothing_happens(container, tmp_path):
    src = _file(container, tmp_path, "x.txt", "x")

    class Off:
        configured = False

    assert _organizer(container, Off()).organize(src.id) == "skipped: no AI model connected"


def test_old_image_facts_are_cleaned_once(container, tmp_path):
    from folio_core.domain.models import ClaimStatus, Extractor, SourceKind

    src = _file(container, tmp_path, "shot.txt", "terminal output")
    container.kdb["sources"].update_one({"_id": src.id}, {"$set": {"kind": SourceKind.IMAGE.value}})
    junk = container.knowledge.create_entity("Tool", "limine-scan")
    chunk = repo.chunks_for_source(container.index.reader(), src.id)[0]
    ev = [{"source_id": src.id, "chunk_id": chunk.id, "locator": chunk.locator.model_dump(exclude_none=True), "quote": "x"}]
    container.knowledge.add_claim(subject_id=junk.id, predicate="version", value="1.0", status=ClaimStatus.PROPOSED,
                                  extractor=Extractor(kind="model", model="groq:m"), evidence=ev)
    keep = container.knowledge.add_claim(subject_id=junk.id, predicate="note", value="mine", status=ClaimStatus.VERIFIED,
                                         extractor=Extractor(kind="model", model="groq:m"), evidence=ev)
    assert container.extraction.cleanup_image_facts() == 1
    assert repo.get_claim(container.kdb, keep) is not None  # confirmed facts stay
    assert container.extraction.cleanup_image_facts() == 0  # only once


def test_extraction_about_facts_never_become_library_tags(container, tmp_path):
    from folio_core.domain.models import ClaimStatus, Extractor

    src = _file(container, tmp_path, "inv.txt", "Invoice #2291")
    _organizer(container, _Model({"title": "Invoice", "description": "d", "tags": [{"name": "Finance"}]})).organize(src.id)
    doc = repo.search_entities(container.kdb, "inv.txt")[0]
    noise = container.knowledge.create_entity("Topic", "Invoice #2291")
    chunk = repo.chunks_for_source(container.index.reader(), src.id)[0]
    container.knowledge.add_claim(subject_id=doc.id, predicate="about", object_id=noise.id, status=ClaimStatus.PROPOSED,
                                  extractor=Extractor(kind="model", model="m", prompt_version="extract-v3-open"),
                                  evidence=[{"source_id": src.id, "chunk_id": chunk.id,
                                             "locator": chunk.locator.model_dump(exclude_none=True), "quote": "Invoice #2291"}])
    assert [t["name"] for t in repo.file_organization(container.kdb, [src.id])[src.id]["tags"]] == ["Finance"]
    assert [t["name"] for t in repo.top_tags(container.kdb)] == ["Finance"]
