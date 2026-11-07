"""Event ledger: append-only, undo/redo, conflict detection, history (FR-7, FR-10)."""

import sqlite3

import pytest

from folio_core.domain.errors import Conflict, NotFound


def test_every_change_is_an_event_and_undo_restores(container):
    k = container.knowledge
    acme = k.create_entity("Organization", "Acme Corp")
    k.update_entity(acme.id, name="ACME Corporation")
    assert container.db.reader().execute("SELECT name FROM entities WHERE id=?", (acme.id,)).fetchone()[0] == "ACME Corporation"

    container.ledger.undo()  # undo the rename
    row = container.db.reader().execute("SELECT name FROM entities WHERE id=?", (acme.id,)).fetchone()
    assert row[0] == "Acme Corp"

    container.ledger.redo()
    row = container.db.reader().execute("SELECT name FROM entities WHERE id=?", (acme.id,)).fetchone()
    assert row[0] == "ACME Corporation"

    history = container.ledger.history("entities", acme.id)
    assert [h["op"] for h in history] == ["insert", "update", "update", "update"]
    assert [h["action"] for h in history][-2:] == ["undo", "redo"]


def test_undo_refuses_when_later_changes_depend_on_it(container):
    k = container.knowledge
    e = k.create_entity("Person", "Priya")
    first = container.ledger.recent_groups(1)[0]["id"]
    k.update_entity(e.id, name="Priya Sharma")
    with pytest.raises(Conflict):
        container.ledger.undo(first)  # creation can't be undone while the rename stands


def test_events_are_append_only(container):
    container.knowledge.create_entity("Person", "Priya")
    with container.db.write() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM events")


def test_nothing_to_undo(container):
    with pytest.raises(NotFound):
        container.ledger.undo()  # schema install is a system action, not user-undoable
