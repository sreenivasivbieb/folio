"""Extraction: schema validation (FR-4), caching (NFR cost), learning from corrections (FR-8)."""

import json
from pathlib import Path

from folio_core.domain.models import ClaimStatus
from folio_core.domain.schema import load_pack
from folio_core.extraction.llm import PROMPT_VERSION, LLMExtractor
from folio_core.extraction.types import CandidateClaim, ExtractionOutput
from folio_core.extraction.validate import validate_output
from folio_core.providers.llm.fake import FakeLLM
from folio_core.store import repo

from .conftest import drain, entity_name, make_container


def _claims(c, predicate=None):
    return repo.query_claims(c.kdb, predicate=predicate)


def _names(c):
    return {d["name"] for d in c.kdb["entities"].find()}


def test_rules_extract_relations_dates_and_provenance(container, files):
    container.ingestion.add_root(str(files / "meeting-notes.md"))
    drain(container)
    owns = _claims(container, "owns")[0]
    ents = repo.get_entities(container.kdb, [owns.subject_id, owns.object_id])
    assert (ents[owns.subject_id].name, ents[owns.object_id].name) == ("Priya Sharma", "Acme Contract")
    assert ents[owns.object_id].type == "Contract"
    assert owns.status == ClaimStatus.PROPOSED
    assert owns.extractor.kind == "model" and owns.extractor.model == "rules-v1"
    ev = owns.evidence[0]
    assert ev.quote in Path(files / "meeting-notes.md").read_text()
    signed = _claims(container, "signed_on")[0]
    assert signed.value == "2026-03-03" and signed.valid_from == "2026-03-03"


def test_validation_rejects_invented_quotes_but_accepts_any_type():
    schema = load_pack()
    out = ExtractionOutput(claims=[
        CandidateClaim(subject="Priya", subject_type="Person", predicate="owns", object="X",
                       object_type="Contract", confidence=0.9, quote="Priya owns X"),
        CandidateClaim(subject="Priya", subject_type="Person", predicate="owns", object="X",
                       object_type="Contract", confidence=0.9, quote="something never said"),
        CandidateClaim(subject="Priya", subject_type="Starship Captain", predicate="commands", object="X",
                       object_type="Starship", confidence=0.9, quote="Priya owns X"),
        CandidateClaim(subject="Priya", subject_type="Person", predicate="owns", confidence=0.9,
                       quote="Priya owns X"),  # attribute without a value
    ])
    valid, problems = validate_output(out, schema, "Hello. Priya   owns X today.")
    assert len(valid.claims) == 2 and len(problems) == 2


GOOD = {"entities": [], "claims": [{
    "subject": "Priya Sharma", "subject_type": "Person", "predicate": "owns", "object": "Acme Contract",
    "object_type": "Contract", "confidence": 0.8, "quote": "Priya Sharma owns the Acme Contract"}]}


def test_llm_extractor_retries_once_then_reports(tmp_path, files):
    llm = FakeLLM(["not json", json.dumps(GOOD)])
    c = make_container(tmp_path, llm=llm, extractor=LLMExtractor(llm))
    c.ingestion.add_root(str(files / "meeting-notes.md"))
    drain(c)
    assert len(llm.calls) == 2  # first answer invalid -> one retry with feedback
    assert "problems" in llm.calls[1][1]
    owns = _claims(c, "owns")[0]
    assert owns.extractor.prompt_version == PROMPT_VERSION

    bad = FakeLLM(["nope"])
    c2 = make_container(tmp_path / "two", llm=bad, extractor=LLMExtractor(bad))
    c2.ingestion.add_root(str(files / "meeting-notes.md"))
    drain(c2)
    issues = c2.review.queue()["extraction_issues"]
    assert issues and "invalid JSON" in issues[0]["reason"]


def test_rerun_on_unchanged_data_makes_zero_model_calls(tmp_path, files):
    llm = FakeLLM([GOOD])
    c = make_container(tmp_path, llm=llm, extractor=LLMExtractor(llm))
    c.ingestion.add_root(str(files / "meeting-notes.md"))
    drain(c)
    calls = len(llm.calls)
    src = repo.list_sources(c.kdb)[0]
    c.queue.enqueue("extract_source", {"source_id": src.id})  # explicit re-extraction
    drain(c)
    assert len(llm.calls) == calls
    assert "cached" in c.queue.list("done", 1)[0].message


def test_rejected_claim_is_never_reproposed_and_verified_is_never_changed(container, files):
    path = files / "meeting-notes.md"
    container.ingestion.add_root(str(path))
    drain(container)
    owns = _claims(container, "owns")[0]
    signed = _claims(container, "signed_on")[0]
    container.knowledge.set_claim_status([owns.id], ClaimStatus.REJECTED)
    container.knowledge.set_claim_status([signed.id], ClaimStatus.VERIFIED)

    path.write_text(path.read_text() + "\nUnrelated line.\n")  # file changes -> full re-extraction
    container.ingestion.scan_path(path)
    drain(container)

    owns_now = _claims(container, "owns")
    assert [c.status for c in owns_now] == [ClaimStatus.REJECTED]
    assert repo.get_claim(container.kdb, signed.id).status == ClaimStatus.VERIFIED
    assert "blocked" in container.queue.list("done", 1)[0].message


def test_correction_rejects_original_and_blocks_its_pattern(container, files):
    container.ingestion.add_root(str(files / "meeting-notes.md"))
    drain(container)
    owns = _claims(container, "owns")[0]
    rahul = container.knowledge.create_entity("Person", "Rahul Verma (manual)")
    new_id = container.knowledge.edit_claim(owns.id, {"subject_id": rahul.id})
    conn = container.kdb
    assert repo.get_claim(conn, owns.id).status == ClaimStatus.REJECTED
    fixed = repo.get_claim(conn, new_id)
    assert fixed.status == ClaimStatus.VERIFIED and fixed.subject_id == rahul.id
    assert fixed.extractor.kind == "user"
    # The correction keeps the source passages the original fact was found in.
    assert [(e.source_id, e.quote) for e in fixed.evidence] == [(e.source_id, e.quote) for e in owns.evidence]
    assert fixed.evidence and {e.id for e in fixed.evidence}.isdisjoint({e.id for e in owns.evidence})


def test_merge_suggestions_for_similar_names(container, tmp_path):
    f = tmp_path / "a.md"
    f.write_text("Priya Sharma works at Acme Corp.\n\nRahul Verma works at Acme Corporation.\n")
    container.ingestion.add_root(str(f))
    drain(container)
    sugg = container.review.queue()["merge_suggestions"]
    names = {entity_name(container, x) for s in sugg for x in (s["entity_a"], s["entity_b"])}
    assert {"Acme Corp", "Acme Corporation"} <= names
    assert "Acme Corp" in _names(container)
