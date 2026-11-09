"""Voice/typed labels (FR-3): preview, questions instead of guesses, confirm, undo."""

import pytest

from folio_core.domain.errors import Conflict
from folio_core.domain.models import ClaimStatus
from folio_core.store import repo

from .conftest import drain


@pytest.fixture
def pdf_source(container, files):
    container.ingestion.add_root(str(files / "contract.pdf"))
    drain(container)
    return repo.list_sources(container.kdb)[0]


def test_the_proposal_example_end_to_end(container, pdf_source):
    labels = container.labels
    label = labels.preview("This PDF is the Acme contract, Priya owns it, signed March 3",
                           "source", [pdf_source.id])
    plan = label.parsed
    refs = {r["name"]: r for r in plan["refs"].values()}
    assert refs["Acme contract"]["type"] == "Contract"
    assert refs["Priya"]["type"] is None  # owns allows Person or Organization -> ask
    assert plan["questions"][0]["options"] == [{"label": "Person", "value": "Person"},
                                               {"label": "Organization", "value": "Organization"}]
    assert any(op["op"] == "attribute" and op["value"].endswith("-03-03") for op in plan["ops"])
    assert not plan["unparsed"]

    with pytest.raises(Conflict):
        labels.confirm(label.id)  # questions still open
    labels.answer(label.id, plan["questions"][0]["id"], "Person")
    done = labels.confirm(label.id)
    assert done.status == "committed"

    conn = container.kdb
    acme = repo.search_entities(conn, "Acme contract", ["Contract"])[0]
    claims = repo.claims_for_entity(conn, acme.id)
    preds = {c.predicate for c in claims}
    assert {"represented_by", "owns", "signed_on"} <= preds
    for c in claims:
        if c.extractor.kind == "voice":
            assert c.status == ClaimStatus.VERIFIED
            assert c.evidence[0].locator.kind == "label" and c.evidence[0].quote.startswith("This PDF")

    # One Ctrl+Z undoes the whole label.
    container.ledger.undo()
    assert repo.search_entities(conn, "Acme contract", ["Contract"]) == []


def test_schema_constraints_disambiguate_else_ask_which_one(container):
    k = container.knowledge
    person = k.create_entity("Person", "Alex")
    org = k.create_entity("Organization", "Alex")
    target = k.create_entity("Project", "Atlas")

    # 'leads' only allows a Person subject, so "Alex" is unambiguous.
    label = container.labels.preview("Alex leads it", "entity", [target.id])
    assert label.parsed["questions"] == []
    lead = next(r for r in label.parsed["refs"].values() if r["name"] == "Alex")
    assert lead["entity_id"] == person.id

    # 'owns' allows Person or Organization: ask, never guess.
    label = container.labels.preview("Alex owns it", "entity", [target.id])
    q = label.parsed["questions"][0]
    assert q["field"] == "entity_id"
    assert {o["value"] for o in q["options"]} == {person.id, org.id}
    container.labels.answer(label.id, q["id"], org.id)
    container.labels.confirm(label.id)
    owns = repo.query_claims(container.kdb, predicate="owns")[0]
    assert owns.subject_id == org.id


def test_reject_and_correct_a_claim_by_voice(container):
    k = container.knowledge
    raj = k.create_entity("Person", "Raj")
    contract = k.create_entity("Contract", "Acme contract")
    from folio_core.domain.models import Extractor

    wrong = k.add_claim(subject_id=raj.id, predicate="owns", object_id=contract.id,
                        status=ClaimStatus.PROPOSED, extractor=Extractor(kind="user"))
    k.create_entity("Person", "Priya")
    label = container.labels.preview("this is wrong, the owner is Priya", "claim", [wrong])
    assert [op["op"] for op in label.parsed["ops"]] == ["claim_status", "relation"]
    container.labels.confirm(label.id)
    conn = container.kdb
    assert repo.get_claim(conn, wrong).status == ClaimStatus.REJECTED
    owners = [c for c in repo.query_claims(conn, predicate="owns") if c.status == ClaimStatus.VERIFIED]
    assert repo.get_entity(conn, owners[0].subject_id).name == "Priya"


def test_unparsed_clauses_are_reported_not_guessed(container, pdf_source):
    label = container.labels.preview("blah blah something", "source", [pdf_source.id])
    assert label.parsed["unparsed"] == ["blah blah something"]
    assert label.parsed["ops"] == []


def test_voice_without_speech_model_is_a_clear_error(container):
    from folio_core.domain.errors import Unavailable

    with pytest.raises(Unavailable):
        container.labels.start("none", [])


def test_first_name_asks_did_you_mean(container):
    k = container.knowledge
    priya = k.create_entity("Person", "Priya Sharma")
    contract = k.create_entity("Contract", "Acme contract")
    label = container.labels.preview("Priya owns it", "entity", [contract.id])
    q = label.parsed["questions"][0]
    assert q["field"] == "entity_id"
    assert [o["value"] for o in q["options"]] == [priya.id, "__new__"]

    # Choosing "new" then asks what the new entity is (owns allows Person or Organization).
    label = container.labels.answer(label.id, q["id"], "__new__")
    q2 = label.parsed["questions"][0]
    assert q2["field"] == "type" and {o["value"] for o in q2["options"]} == {"Person", "Organization"}

    label = container.labels.preview("Priya owns it", "entity", [contract.id])
    container.labels.answer(label.id, label.parsed["questions"][0]["id"], priya.id)
    container.labels.confirm(label.id)
    owns = [c for c in repo.query_claims(container.kdb, predicate="owns")]
    assert owns[0].subject_id == priya.id


def test_naming_an_auto_entity_in_a_label_verifies_it(container):
    from folio_core.domain.models import EntityStatus

    with container.ledger.group("model:test", "extract") as tx:
        row = container.knowledge.create_entity_tx(tx, "Contract", "Acme contract", actor="model:test",
                                                   status=EntityStatus.AUTO)
    container.knowledge.create_entity("Person", "Priya")
    label = container.labels.preview("Priya owns the Acme contract", "none", [])
    container.labels.confirm(label.id)
    assert repo.get_entity(container.kdb, row["id"]).status == EntityStatus.VERIFIED


def test_translated_hindi_label_shapes_are_understood(container, pdf_source):
    """What Whisper's translate mode returns for 'Yeh Acme ka contract hai. Priya iski maalik hai.'"""
    label = container.labels.preview("This is the contract of Acme. Priya is its owner.", "source", [pdf_source.id])
    plan = label.parsed
    assert not plan["unparsed"]
    refs = {r["name"]: r for r in plan["refs"].values()}
    assert refs["Acme contract"]["type"] == "Contract"
    assert [op["op"] for op in plan["ops"]] == ["represent", "relation"]
    assert plan["ops"][1]["predicate"] == "owns"
    other = container.labels.preview("Priya is the owner of this contract", "source", [pdf_source.id])
    assert not other.parsed["unparsed"] and other.parsed["ops"][-1]["predicate"] == "owns"


@pytest.mark.parametrize("spoken", [
    "Tag this as finance", "Topic is finance", "This file is about finance", "label it finance",
    "file this under finance", "category: finance",
])
def test_topic_labels_need_no_questions(container, pdf_source, spoken):
    label = container.labels.preview(spoken, "source", [pdf_source.id])
    plan = label.parsed
    assert not plan["questions"] and not plan["unparsed"]
    topic = next(r for r in plan["refs"].values() if r["name"] == "finance")
    assert topic["type"] == "Topic"
    assert container.labels.confirm(label.id).status == "committed"


def test_topic_lists_and_reuse(container, pdf_source):
    container.labels.confirm(container.labels.preview("this is about taxes, invoices and receipts",
                                                      "source", [pdf_source.id]).id)
    again = container.labels.preview("tag it as taxes", "source", [pdf_source.id]).parsed
    assert [r["new"] for r in again["refs"].values() if r["name"] == "taxes"] == [False]
    assert {e.name for e in repo.search_entities(container.kdb, "", ["Topic"])} == {"taxes", "invoices", "receipts"}


def test_failed_clause_leaves_no_half_plan(container, pdf_source):
    plan = container.labels.preview("It was signed on March 3", "source", [pdf_source.id]).parsed
    assert plan["ops"] == [] and plan["unparsed"]


def test_search_by_topic_finds_labelled_files(container, pdf_source):
    container.labels.confirm(container.labels.preview("tag this as personal finance", "source",
                                                      [pdf_source.id]).id)
    ents = repo.search_entities(container.kdb, "finance")
    files = container.search.files("finance", ents)
    assert [f["source_id"] for f in files] == [pdf_source.id]
    assert container.search.search("quantum chromodynamics") == []  # no random vector neighbours
