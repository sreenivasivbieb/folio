from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pymongo.client_session import ClientSession

from ..domain.errors import Conflict, NotFound
from ..domain.ids import new_id
from ..realtime import Bus
from ..store.index_db import utcnow
from ..store.mongo import KnowledgeDB, to_doc, to_row

# Collections whose documents are user knowledge. Only these are written through the ledger.
TRACKED = frozenset({"settings", "schema_versions", "roots", "entities", "claims", "labels"})

UNDOABLE_ACTORS = ["user", "voice"]


def _check(coll: str) -> None:
    if coll not in TRACKED:
        raise ValueError(f"collection {coll!r} is not ledger-tracked")


class Tx:
    """A ledger transaction: document writes recorded as events of one group. Reads through the
    Tx see the transaction's own uncommitted writes."""

    def __init__(self, kdb: KnowledgeDB, session: ClientSession, group_id: str, actor: str) -> None:
        self.kdb = kdb
        self.session = session
        self.group_id = group_id
        self.actor = actor
        self.undoes: str | None = None
        self.changed: list[tuple[str, str]] = []  # (collection, doc id)

    # --- reads (inside the transaction) ---------------------------------------------------

    def get(self, coll: str, doc_id: str) -> dict[str, Any] | None:
        return to_row(self.kdb[coll].find_one({"_id": doc_id}, session=self.session))

    def find(self, coll: str, query: dict[str, Any], **kw: Any) -> list[dict[str, Any]]:
        return [to_row(d) for d in self.kdb[coll].find(query, session=self.session, **kw)]  # type: ignore[misc]

    # --- writes ---------------------------------------------------------------------------

    def _event(self, coll: str, doc_id: str, op: str, before: Any, after: Any) -> None:
        self.kdb["events"].insert_one({
            "_id": new_id("event"), "seq": self.kdb.next_seq("events", self.session),
            "group_id": self.group_id, "ts": utcnow(), "coll": coll, "doc_id": doc_id, "op": op,
            "before": before, "after": after,
        }, session=self.session)
        self.changed.append((coll, doc_id))

    def insert(self, coll: str, row: dict[str, Any]) -> dict[str, Any]:
        _check(coll)
        self.kdb[coll].insert_one(to_doc(row), session=self.session)
        after = self.get(coll, row["id"])
        self._event(coll, row["id"], "insert", None, after)
        return after  # type: ignore[return-value]

    def update(self, coll: str, doc_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        _check(coll)
        before = self.get(coll, doc_id)
        if before is None:
            raise NotFound(f"{coll} {doc_id} not found")
        real = {k: v for k, v in changes.items() if before.get(k) != v}
        if not real:
            return before
        if "updated_at" in before and "updated_at" not in real:
            real["updated_at"] = utcnow()
        self.kdb[coll].update_one({"_id": doc_id}, {"$set": real}, session=self.session)
        after = self.get(coll, doc_id)
        self._event(coll, doc_id, "update", before, after)
        return after  # type: ignore[return-value]

    def delete(self, coll: str, doc_id: str) -> dict[str, Any] | None:
        _check(coll)
        before = self.get(coll, doc_id)
        if before is None:
            return None
        self.kdb[coll].delete_one({"_id": doc_id}, session=self.session)
        self._event(coll, doc_id, "delete", before, None)
        return before

    def upsert(self, coll: str, row: dict[str, Any]) -> dict[str, Any]:
        if self.get(coll, row["id"]) is None:
            return self.insert(coll, row)
        return self.update(coll, row["id"], {k: v for k, v in row.items() if k != "id"})


class Ledger:
    """Append-only event log. Every durable write goes through ``group()``; see ADR-0004."""

    def __init__(self, kdb: KnowledgeDB, bus: Bus) -> None:
        self.kdb = kdb
        self.bus = bus
        self._local = threading.local()

    @contextmanager
    def group(self, actor: str, action: str, summary: str = "") -> Iterator[Tx]:
        """Open (or join, if nested) a ledger group; commits atomically with all its events."""
        current: Tx | None = getattr(self._local, "tx", None)
        if current is not None:
            yield current
            return
        group_id = new_id("group")
        with self.kdb.transaction() as session:
            tx = Tx(self.kdb, session, group_id, actor)
            self._local.tx = tx
            try:
                yield tx
                if tx.changed:
                    self.kdb["event_groups"].insert_one({
                        "_id": group_id, "seq": self.kdb.next_seq("groups", session), "ts": utcnow(),
                        "actor": actor, "action": action, "summary": summary, "undoes": tx.undoes,
                    }, session=session)
            finally:
                self._local.tx = None
        if tx.changed:
            self.bus.publish({
                "type": "ledger", "group_id": group_id, "actor": actor, "action": action,
                "summary": summary, "tables": sorted({c for c, _ in tx.changed}),
                "rows": [r for _, r in tx.changed][:200],
            })

    # --- undo / redo ----------------------------------------------------------------------

    def _is_undone(self, group_id: str) -> bool:
        reverts = self.kdb["event_groups"].find({"undoes": group_id}, {"_id": 1})
        return any(not self._is_undone(r["_id"]) for r in reverts)

    def undo(self, group_id: str | None = None) -> str:
        """Revert ``group_id`` (default: the latest undoable user action)."""
        if group_id is None:
            rows = self.kdb["event_groups"].find(
                {"actor": {"$in": UNDOABLE_ACTORS}, "action": {"$nin": ["undo", "redo"]}},
                {"_id": 1}).sort("seq", -1).limit(200)
            group_id = next((r["_id"] for r in rows if not self._is_undone(r["_id"])), None)
            if group_id is None:
                raise NotFound("nothing to undo")
        return self._revert(group_id, "undo")

    def redo(self) -> str:
        """Revert the most recent still-active undo. A fresh edit clears the redo stack."""
        rows = self.kdb["event_groups"].find({"actor": {"$in": UNDOABLE_ACTORS}}).sort("seq", -1).limit(200)
        for r in rows:
            if r["action"] == "redo":
                continue
            if r["action"] == "undo":
                if not self._is_undone(r["_id"]):
                    return self._revert(r["_id"], "redo")
                continue
            break
        raise NotFound("nothing to redo")

    def _revert(self, group_id: str, action: str) -> str:
        grp = self.kdb["event_groups"].find_one({"_id": group_id})
        if grp is None:
            raise NotFound(f"event group {group_id} not found")
        if self._is_undone(group_id):
            raise Conflict("that action is already undone")
        events = list(self.kdb["events"].find({"group_id": group_id}).sort("seq", -1))
        summary = f"{action} {grp['action']}" + (f": {grp['summary']}" if grp["summary"] else "")
        with self.group("user", action, summary) as tx:
            tx.undoes = group_id
            for ev in events:
                coll, doc_id, before, after = ev["coll"], ev["doc_id"], ev["before"], ev["after"]
                current = tx.get(coll, doc_id)
                later = Conflict(f"{coll} {doc_id} changed after this action; undo later changes first")
                if ev["op"] == "insert":
                    if current != after:
                        raise later
                    tx.delete(coll, doc_id)
                elif ev["op"] == "update":
                    cols = [k for k in after if before.get(k) != after.get(k) and k != "updated_at"]
                    if current is None or any(current.get(k) != after.get(k) for k in cols):
                        raise later
                    tx.update(coll, doc_id, {k: before.get(k) for k in cols})
                else:
                    if current is not None:
                        raise Conflict(f"{coll} {doc_id} was re-created after this action")
                    tx.insert(coll, before)
            return tx.group_id

    # --- history (FR-10) ------------------------------------------------------------------

    def history(self, coll: str, doc_id: str) -> list[dict[str, Any]]:
        events = list(self.kdb["events"].find({"coll": coll, "doc_id": doc_id}).sort("seq", 1))
        groups = {g["_id"]: g for g in self.kdb["event_groups"].find(
            {"_id": {"$in": list({e["group_id"] for e in events})}})}
        out = []
        for e in events:
            g = groups.get(e["group_id"], {})
            out.append({"seq": e["seq"], "ts": e["ts"], "op": e["op"], "before": e["before"],
                        "after": e["after"], "group_id": e["group_id"], "actor": g.get("actor", "?"),
                        "action": g.get("action", "?"), "summary": g.get("summary", "")})
        return out

    def recent_groups(self, limit: int = 50) -> list[dict[str, Any]]:
        groups = list(self.kdb["event_groups"].find().sort("seq", -1).limit(limit))
        counts = {r["_id"]: r["n"] for r in self.kdb["events"].aggregate([
            {"$match": {"group_id": {"$in": [g["_id"] for g in groups]}}},
            {"$group": {"_id": "$group_id", "n": {"$sum": 1}}},
        ])}
        return [{**to_row(g), "n_events": counts.get(g["_id"], 0), "undone": self._is_undone(g["_id"])}  # type: ignore[dict-item]
                for g in groups]
