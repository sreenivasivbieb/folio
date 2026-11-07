"""The event ledger: append-only record of every create, edit, merge and reject.

Every mutation of durable data (knowledge.db) goes through :class:`Ledger`. A *group* is one
user-visible action ("merge Acme and ACME Corp"); each row it touches is an *event* holding the
row's before/after snapshot. That one structure gives us:

* **undo / redo** — revert a group by restoring its snapshots (recorded as a new group),
* **audit / provenance** (FR-10) — the full history of any claim or entity,
* **learning** — corrections are just events the learning store can read,
* **sync later** — the log is the replication unit if multi-device ever ships.
"""

from .ledger import TRACKED_TABLES, Ledger, Tx

__all__ = ["Ledger", "Tx", "TRACKED_TABLES"]
