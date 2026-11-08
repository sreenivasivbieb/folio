"""Event ledger: atomic groups, undo/redo, conflict detection, history (FR-7, FR-10)."""

import pytest

from folio_core.domain.errors import Conflict, NotFound

from .conftest import entity_name


def test_every_change_is_an_event_and_undo_restores(container):
    k = container.knowledge
    acme = k.create_entity("Organization", "Acme Corp")
    k.update_entity(acme.id, name="ACME Corporation")
    assert entity_name(container, acme.id) == "ACME Corporation"

    container.ledger.undo()  # undo the rename (name + the alias it added) in one step
    assert entity_name(container, acme.id) == "Acme Corp"
    assert [a["alias"] for a in container.kdb["entities"].find_one({"_id": acme.id})["aliases"]] == ["Acme Corp"]

    container.ledger.redo()
    assert entity_name(container, acme.id) == "ACME Corporation"

    history = container.ledger.history("entities", acme.id)
    assert history[0]["op"] == "insert" and history[0]["actor"] == "user"
    assert [h["action"] for h in history][-1] == "redo"


def test_undo_refuses_when_later_changes_depend_on_it(container):
    k = container.knowledge
    e = k.create_entity("Person", "Priya")
    first = container.ledger.recent_groups(1)[0]["id"]
    k.update_entity(e.id, name="Priya Sharma")
    with pytest.raises(Conflict):
        container.ledger.undo(first)  # creation can't be undone while the rename stands


def test_ledger_is_append_only_and_atomic(container):
    k = container.knowledge
    k.create_entity("Person", "Priya")
    before = list(container.kdb["events"].find().sort("seq", 1))
    container.ledger.undo()
    container.ledger.redo()
    after = list(container.kdb["events"].find().sort("seq", 1))
    assert after[: len(before)] == before  # nothing earlier was changed or removed
    assert [e["seq"] for e in after] == sorted(e["seq"] for e in after)

    # A failing action leaves no trace: entity, alias and event roll back together.
    with pytest.raises(RuntimeError), container.ledger.group("user", "boom") as tx:
        container.knowledge.create_entity_tx(tx, "Person", "Ghost", actor="user")
        raise RuntimeError("crash mid-action")
    assert container.kdb["entities"].count_documents({"name": "Ghost"}) == 0
    assert container.kdb["events"].count_documents({}) == len(after)


def test_nothing_to_undo(container):
    with pytest.raises(NotFound):
        container.ledger.undo()  # schema install is a system action, not user-undoable
