"""The knowledge store: MongoDB (run it with ``docker compose up -d`` at the repo root).

Open schema: documents are free-form JSON. Entity types, attribute names and relation names are
whatever the user or the model says — there are no fixed categories. What *is* fixed is the
small envelope that makes the data trustworthy: ids, status, provenance (extractor), evidence and
the ledger.

Collections (``_id`` is our prefixed string id, see domain/ids.py):

    settings        {_id: key, value}
    schema_versions {_id, version, name, definition, created_at}       type *hints*, not rules
    roots           {_id, path, kind, watch, created_at}
    sources         {_id, root_id, path, kind, size, mtime, content_hash, indexed_hash, status, ...}
    entities        {_id, type, name, status, created_by, merged_into, aliases: [...], ...}
    claims          {_id, subject_id, predicate, kind, value, object_id, valid_from, ...,
                     extractor: {...}, fingerprint, evidence: [{id, source_id, locator, quote, ...}]}
    labels          {_id, transcript, audio_path, target_kind, target_ids, parsed, status, ...}
    event_groups    {_id, seq, ts, actor, action, summary, undoes}     append-only (ledger/)
    events          {_id, seq, group_id, ts, coll, doc_id, op, before, after}
    counters        {_id: name, seq}

Writes that must be atomic (every ledger group) run in a multi-document transaction, which is why
MongoDB runs as a single-node replica set. As with SQLite before, there is a single writer per
process: a lock serialises transactions so our own threads never conflict.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.client_session import ClientSession
from pymongo.collection import Collection
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from ..domain.errors import Unavailable

INDEXES: dict[str, list[tuple[list[tuple[str, int]], dict[str, Any]]]] = {
    "roots": [([("path", ASCENDING)], {"unique": True})],
    "sources": [([("path", ASCENDING)], {"unique": True}), ([("root_id", ASCENDING)], {})],
    "entities": [([("aliases.normalized", ASCENDING)], {}), ([("type", ASCENDING), ("status", ASCENDING)], {})],
    "claims": [
        ([("subject_id", ASCENDING)], {}),
        ([("object_id", ASCENDING)], {}),
        ([("fingerprint", ASCENDING)], {}),
        ([("status", ASCENDING), ("confidence", ASCENDING)], {}),
        ([("valid_from", ASCENDING)], {}),
        ([("predicate", ASCENDING)], {}),
        ([("evidence.source_id", ASCENDING)], {}),
    ],
    "labels": [([("created_at", DESCENDING)], {})],
    "event_groups": [([("seq", ASCENDING)], {"unique": True}), ([("undoes", ASCENDING)], {})],
    "events": [([("coll", ASCENDING), ("doc_id", ASCENDING), ("seq", ASCENDING)], {}),
               ([("group_id", ASCENDING)], {})],
}


def to_row(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Mongo document -> plain dict with ``id`` instead of ``_id``."""
    if doc is None:
        return None
    out = dict(doc)
    out["id"] = out.pop("_id")
    return out


def to_doc(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["_id"] = out.pop("id")
    return out


class KnowledgeDB:
    def __init__(self, uri: str, name: str, timeout_ms: int = 5000, wait_s: float = 20.0) -> None:
        self.uri = uri
        self.name = name
        self.client: MongoClient[dict[str, Any]] = MongoClient(
            uri, serverSelectionTimeoutMS=timeout_ms, appname="folio-core"
        )
        deadline = time.monotonic() + wait_s  # the container may still be starting (e.g. after boot)
        while True:
            try:
                self.client.admin.command("ping")
                break
            except ServerSelectionTimeoutError as exc:
                if time.monotonic() >= deadline:
                    raise Unavailable(
                        f"cannot reach MongoDB at {uri}. Start it with `docker compose up -d` in the "
                        "Folio folder (or set FOLIO_MONGO_URI)."
                    ) from exc
        self.db = self.client[name]
        self._write_lock = threading.RLock()
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        for coll, specs in INDEXES.items():
            for keys, opts in specs:
                self.db[coll].create_index(keys, **opts)

    def __getitem__(self, name: str) -> Collection[dict[str, Any]]:
        return self.db[name]

    @contextmanager
    def transaction(self) -> Iterator[ClientSession]:
        """One atomic multi-document transaction (serialised within this process)."""
        with self._write_lock, self.client.start_session() as session:
            session.start_transaction()
            try:
                yield session
            except BaseException:
                if session.in_transaction:
                    session.abort_transaction()
                raise
            self._commit(session)

    @staticmethod
    def _commit(session: ClientSession) -> None:
        for attempt in range(3):
            try:
                session.commit_transaction()
                return
            except PyMongoError as exc:
                if attempt < 2 and exc.has_error_label("UnknownTransactionCommitResult"):
                    continue
                raise

    def next_seq(self, counter: str, session: ClientSession | None = None) -> int:
        doc = self.db["counters"].find_one_and_update(
            {"_id": counter}, {"$inc": {"seq": 1}}, upsert=True,
            return_document=ReturnDocument.AFTER, session=session,
        )
        return int(doc["seq"])

    def drop(self) -> None:
        """Delete the whole database (tests)."""
        self.client.drop_database(self.name)

    def close(self) -> None:
        self.client.close()
