"""Inline editing: merge / split / retype / reject, all undoable (FR-7)."""

import pytest

from folio_core.domain.errors import InvalidInput
from folio_core.domain.models import ClaimStatus, EntityStatus, Extractor
from folio_core.store import repo


def _rel(k, s, p, o):
    return k.add_claim(subject_id=s, predicate=p, object_id=o, status=ClaimStatus.VERIFIED,
                       extractor=Extractor(kind="user"))


def test_merge_moves_claims_adds_aliases_and_undoes_cleanly(container):
    k, conn = container.knowledge, container.db.reader()
    a = k.create_entity("Organization", "Acme Corp")
    b = k.create_entity("Organization", "ACME Corporation")
    priya = k.create_entity("Person", "Priya")
    _rel(k, priya.id, "works_at", a.id)
    dup = _rel(k, priya.id, "works_at", b.id)  # same fact once merged

    merged = k.merge_entities(a.id, b.id)
    assert "ACME Corporation" in merged.aliases
    assert repo.get_entity(conn, b.id).status == EntityStatus.MERGED
    works = repo.query_claims(conn, predicate="works_at")
    assert len(works) == 1 and works[0].object_id == a.id  # duplicates collapsed
    assert repo.resolve_merged(conn, b.id) == a.id

    container.ledger.undo()
    assert repo.get_entity(conn, b.id).status == EntityStatus.VERIFIED
    assert repo.get_claim(conn, dup).object_id == b.id
    assert "ACME Corporation" not in repo.get_entity(conn, a.id).aliases


def test_split_moves_selected_claims(container):
    k, conn = container.knowledge, container.db.reader()
    jordan = k.create_entity("Person", "Jordan")
    acme = k.create_entity("Organization", "Acme")
    beta = k.create_entity("Organization", "Beta")
    c1 = _rel(k, jordan.id, "works_at", acme.id)
    _rel(k, jordan.id, "works_at", beta.id)
    other = k.split_entity(jordan.id, "Jordan (Beta)", [c1])
    assert repo.get_claim(conn, c1).subject_id == other.id


def test_schema_guards_claims(container):
    k = container.knowledge
    priya = k.create_entity("Person", "Priya")
    project = k.create_entity("Project", "Atlas")
    with pytest.raises(InvalidInput):
        _rel(k, project.id, "works_at", priya.id)  # Project cannot work at a Person
    with pytest.raises(InvalidInput):
        k.add_claim(subject_id=priya.id, predicate="email", value="not-an-email",
                    status=ClaimStatus.VERIFIED, extractor=Extractor(kind="user"))
    with pytest.raises(InvalidInput):
        k.create_entity("Spaceship", "Enterprise")


def test_rejecting_entity_rejects_its_proposed_claims(container):
    k, conn = container.knowledge, container.db.reader()
    ghost = k.create_entity("Person", "Ghost")
    acme = k.create_entity("Organization", "Acme")
    cid = k.add_claim(subject_id=ghost.id, predicate="works_at", object_id=acme.id,
                      status=ClaimStatus.PROPOSED, extractor=Extractor(kind="user"))
    # a user add of an identical fact verifies; force proposed for the test
    with container.ledger.group("system", "test") as tx:
        tx.update("claims", cid, {"status": "proposed"})
    k.update_entity(ghost.id, status=EntityStatus.REJECTED)
    assert repo.get_claim(conn, cid).status == ClaimStatus.REJECTED


def test_schema_update_creates_new_version(container):
    v1, schema = container.knowledge.schema()
    schema.entity_types["Invoice"] = schema.entity_types["Document"].model_copy()
    v2 = container.knowledge.update_schema(schema)
    assert v2 == v1 + 1
    assert "Invoice" in container.knowledge.schema()[1].entity_types
