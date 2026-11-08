"""The event ledger: append-only record of every create, edit, merge and reject.

Every mutation of durable knowledge (MongoDB) goes through :class:`Ledger`. A *group* is one
user-visible action ("merge Acme and ACME Corp"); each document it touches is an *event* with
before/after snapshots, written in the same MongoDB transaction. That one structure gives us:

* **undo / redo** — revert a group by restoring its snapshots (recorded as a new group),
* **audit / provenance** (FR-10) — the full history of any claim or entity,
* **learning** — corrections are just events the learning store can read,
* **sync later** — the log is the replication unit if multi-device ever ships.

Append-only is enforced by the code path: nothing in the codebase updates or deletes
``events`` / ``event_groups``.
"""

from .ledger import TRACKED, Ledger, Tx

__all__ = ["Ledger", "Tx", "TRACKED"]
