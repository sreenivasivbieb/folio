from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..domain.errors import Conflict, NotFound
from ..domain.ids import new_id
from ..realtime import Bus
from ..store.db import Database, dumps, loads, utcnow

# Tables whose rows are user knowledge. Only these are written through the ledger.
TRACKED_TABLES = frozenset(
    {"settings", "schema_versions", "roots", "entities", "aliases", "claims", "evidence", "labels"}
)

UNDOABLE_ACTORS = ("user", "voice")


class Tx:
    """A ledger transaction: row-level writes that are recorded as events of one group."""

    def __init__(self, conn: sqlite3.Connection, group_id: str, actor: str) -> None:
        self.conn = conn
        self.group_id = group_id
        self.actor = actor
        self.changed: list[tuple[str, str]] = []  # (table, row_id)

    # --- primitives -----------------------------------------------------------------------

    def _row(self, table: str, row_id: str) -> dict[str, Any] | None:
        _check(table)
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(row) if row else None

    def _event(self, table: str, row_id: str, op: str, before: Any, after: Any) -> None:
        self.conn.execute(
            "INSERT INTO events(id, group_id, ts, tbl, row_id, op, before, after) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("event"), self.group_id, utcnow(), table, row_id, op,
             dumps(before) if before is not None else None,
             dumps(after) if after is not None else None),
        )
        self.changed.append((table, row_id))

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        _check(table)
        cols = list(row)
        self.conn.execute(
            f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [row[c] for c in cols],
        )
        after = self._row(table, row["id"])
        self._event(table, row["id"], "insert", None, after)
        return after  # type: ignore[return-value]

    def update(self, table: str, row_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        before = self._row(table, row_id)
        if before is None:
            raise NotFound(f"{table} {row_id} not found")
        real = {k: v for k, v in changes.items() if before.get(k) != v}
        if not real:
            return before
        if "updated_at" in before and "updated_at" not in real:
            real["updated_at"] = utcnow()
        sets = ", ".join(f"{k} = ?" for k in real)
        self.conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*real.values(), row_id])
        after = self._row(table, row_id)
        self._event(table, row_id, "update", before, after)
        return after  # type: ignore[return-value]

    def delete(self, table: str, row_id: str) -> dict[str, Any] | None:
        before = self._row(table, row_id)
        if before is None:
            return None
        self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        self._event(table, row_id, "delete", before, None)
        return before

    def upsert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        if self._row(table, row["id"]) is None:
            return self.insert(table, row)
        return self.update(table, row["id"], {k: v for k, v in row.items() if k != "id"})


def _check(table: str) -> None:
    if table not in TRACKED_TABLES:
        raise ValueError(f"table {table!r} is not ledger-tracked")


class Ledger:
    def __init__(self, db: Database, bus: Bus) -> None:
        self.db = db
        self.bus = bus
        self._local = threading.local()

    @contextmanager
    def group(self, actor: str, action: str, summary: str = "") -> Iterator[Tx]:
        """Open (or join, if nested) a ledger group. Commits atomically with all its events."""
        current: Tx | None = getattr(self._local, "tx", None)
        if current is not None:
            yield current
            return
        group_id = new_id("group")
        with self.db.write() as conn:
            tx = Tx(conn, group_id, actor)
            self._local.tx = tx
            try:
                yield tx
                if tx.changed:
                    conn.execute(
                        "INSERT INTO event_groups(id, ts, actor, action, summary, undoes) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (group_id, utcnow(), actor, action, summary, getattr(tx, "undoes", None)),
                    )
            finally:
                self._local.tx = None
        if tx.changed:
            self.bus.publish({
                "type": "ledger",
                "group_id": group_id,
                "actor": actor,
                "action": action,
                "summary": summary,
                "tables": sorted({t for t, _ in tx.changed}),
                "rows": [r for _, r in tx.changed][:200],
            })

    # --- undo / redo ----------------------------------------------------------------------

    def _is_undone(self, conn: sqlite3.Connection, group_id: str) -> bool:
        reverts = conn.execute("SELECT id FROM event_groups WHERE undoes = ?", (group_id,)).fetchall()
        return any(not self._is_undone(conn, r[0]) for r in reverts)

    def undo(self, group_id: str | None = None) -> str:
        """Revert ``group_id`` (default: the latest undoable user action). Returns the new group id."""
        conn = self.db.reader()
        if group_id is None:
            marks = ",".join("?" * len(UNDOABLE_ACTORS))
            rows = conn.execute(
                f"SELECT id FROM event_groups WHERE actor IN ({marks}) "
                f"AND action NOT IN ('undo', 'redo') ORDER BY seq DESC LIMIT 200",
                UNDOABLE_ACTORS,
            ).fetchall()
            group_id = next((r[0] for r in rows if not self._is_undone(conn, r[0])), None)
            if group_id is None:
                raise NotFound("nothing to undo")
        return self._revert(group_id, "undo")

    def redo(self) -> str:
        """Revert the most recent still-active undo. A fresh edit clears the redo stack."""
        conn = self.db.reader()
        rows = conn.execute(
            "SELECT id, action FROM event_groups WHERE actor IN ('user','voice') ORDER BY seq DESC LIMIT 200"
        ).fetchall()
        for r in rows:
            if r["action"] == "redo":
                continue
            if r["action"] == "undo":
                if not self._is_undone(conn, r["id"]):
                    return self._revert(r["id"], "redo")
                continue
            break
        raise NotFound("nothing to redo")

    def _revert(self, group_id: str, action: str) -> str:
        conn = self.db.reader()
        grp = conn.execute("SELECT * FROM event_groups WHERE id = ?", (group_id,)).fetchone()
        if grp is None:
            raise NotFound(f"event group {group_id} not found")
        if self._is_undone(conn, group_id):
            raise Conflict("that action is already undone")
        events = conn.execute(
            "SELECT * FROM events WHERE group_id = ? ORDER BY seq DESC", (group_id,)
        ).fetchall()
        summary = f"{action} {grp['action']}" + (f": {grp['summary']}" if grp["summary"] else "")
        with self.group("user", action, summary) as tx:
            tx.undoes = group_id  # type: ignore[attr-defined]
            for ev in events:
                table, row_id = ev["tbl"], ev["row_id"]
                before, after = loads(ev["before"]), loads(ev["after"])
                current = tx._row(table, row_id)
                if ev["op"] == "insert":
                    if current != after:
                        raise Conflict(f"{table} {row_id} changed after this action; undo later changes first")
                    tx.delete(table, row_id)
                elif ev["op"] == "update":
                    changed_cols = [k for k in after if before.get(k) != after.get(k) and k != "updated_at"]
                    if current is None or any(current.get(k) != after.get(k) for k in changed_cols):
                        raise Conflict(f"{table} {row_id} changed after this action; undo later changes first")
                    tx.update(table, row_id, {k: before[k] for k in changed_cols})
                else:  # delete
                    if current is not None:
                        raise Conflict(f"{table} {row_id} was re-created after this action")
                    tx.insert(table, before)
            return tx.group_id

    # --- history (FR-10) ------------------------------------------------------------------

    def history(self, table: str, row_id: str) -> list[dict[str, Any]]:
        rows = self.db.reader().execute(
            "SELECT e.seq, e.ts, e.op, e.before, e.after, g.id AS group_id, g.actor, g.action, g.summary "
            "FROM events e JOIN event_groups g ON g.id = e.group_id "
            "WHERE e.tbl = ? AND e.row_id = ? ORDER BY e.seq",
            (table, row_id),
        ).fetchall()
        return [
            {**dict(r), "before": loads(r["before"]), "after": loads(r["after"])} for r in rows
        ]

    def recent_groups(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self.db.reader()
        rows = conn.execute(
            "SELECT g.*, (SELECT COUNT(*) FROM events e WHERE e.group_id = g.id) AS n_events "
            "FROM event_groups g ORDER BY g.seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{**dict(r), "undone": self._is_undone(conn, r["id"])} for r in rows]
