"""Embedded, user-owned knowledge file. No server, account, network or external database.

The small document interface keeps the domain and ledger independent of persistence. JSON
records live in one private SQLite file, with real transactions and indexed path lookups.
"""

from __future__ import annotations

import json
import operator
import os
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..domain.errors import Conflict
from .maintenance import compact, enable_incremental_on_new


class WriteConflict(Conflict):
    pass


class Session:
    pass


def to_row(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return {"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}}


def to_doc(row: dict[str, Any]) -> dict[str, Any]:
    return {"_id": row["id"], **{k: v for k, v in row.items() if k != "id"}}


def _values(doc: Any, path: str) -> list[Any]:
    if not path:
        return doc if isinstance(doc, list) else [doc]
    head, _, tail = path.partition(".")
    if isinstance(doc, list):
        if head.isdigit():
            return _values(doc[int(head)], tail) if int(head) < len(doc) else []
        return [v for item in doc for v in _values(item, path)]
    return _values(doc[head], tail) if isinstance(doc, dict) and head in doc else []


def matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, condition in query.items():
        if key == "$or":
            if not any(matches(doc, q) for q in condition):
                return False
            continue
        if key == "$and":
            if not all(matches(doc, q) for q in condition):
                return False
            continue
        values = _values(doc, key)
        if not isinstance(condition, dict):
            if not any(v == condition for v in values) and not (condition is None and not values):
                return False
            continue
        for op, wanted in condition.items():
            if op == "$options":
                continue
            if op == "$exists":
                ok = bool(values) == bool(wanted)
            elif op == "$in":
                ok = any(v in wanted for v in values)
            elif op == "$nin":
                ok = not any(v in wanted for v in values)
            elif op == "$ne":
                ok = not any(v == wanted for v in values) and (wanted is not None or bool(values))
            elif op == "$regex":
                flags = re.I if "i" in condition.get("$options", "") else 0
                ok = any(re.search(wanted, str(v), flags) for v in values)
            else:
                comparisons = {"$gt": operator.gt, "$gte": operator.ge, "$lt": operator.lt, "$lte": operator.le}
                if op not in comparisons:
                    raise ValueError(f"unsupported record filter: {op}")
                ok = any(v is not None and comparisons[op](v, wanted) for v in values)
            if not ok:
                return False
    return True


def _expression(field: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z_][\w.]*", field) or field.split(".")[0] in ARRAY_FIELDS:
        return None
    return "id" if field == "_id" else f"json_extract(body, '$.{field}')"


ARRAY_FIELDS = frozenset({"aliases", "evidence"})  # lists of objects inside a record


def _array_where(field: str, condition: Any) -> tuple[str, list[Any]] | None:
    """``evidence.source_id`` style filters ("any element matches") as SQL over json_each, so
    forgetting a file or resolving a name no longer scans every record in Python."""
    head, _, tail = field.partition(".")
    if not re.fullmatch(r"[A-Za-z_]\w*", tail):
        return None
    element = f"json_extract(_e.value, '$.{tail}')"
    source = f"json_each(documents.body, '$.{head}') AS _e"
    if not isinstance(condition, dict):
        condition = {"$eq": condition}
    clauses, args = [], []
    for op, value in condition.items():
        if op == "$options":
            continue
        if value is None:
            return None  # "missing" vs null differ between the two engines: use the exact one
        if op in ("$in", "$nin"):
            if not value:
                clauses.append("1" if op == "$nin" else "0")
                continue
            test, arg = f"{element} IN (SELECT value FROM json_each(?))", json.dumps(value)
        elif op == "$regex":
            test = f"{element} REGEXP ?"
            arg = ("(?i)" if "i" in condition.get("$options", "") else "") + value
        elif op in {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte"}:
            symbol = {"$eq": "=", "$ne": "=", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
            test, arg = f"{element} {symbol} ?", value
        else:
            return None
        negate = op in ("$ne", "$nin")  # "no element equals"
        clauses.append(f"{'NOT ' if negate else ''}EXISTS (SELECT 1 FROM {source} WHERE {test})")
        args.append(arg)
    return " AND ".join(clauses) or "1", args


def _where(query: dict[str, Any]) -> tuple[str, list[Any]] | None:
    clauses, args = [], []
    for field, condition in query.items():
        if field in ("$or", "$and"):
            sub = [_where(q) for q in condition]
            if any(q is None for q in sub):
                return None
            clauses.append("(" + (" OR " if field == "$or" else " AND ").join(q[0] for q in sub) + ")")
            args += [a for q in sub for a in q[1]]
            continue
        if field.split(".")[0] in ARRAY_FIELDS:
            compiled = _array_where(field, condition)
            if compiled is None:
                return None
            clauses.append(compiled[0])
            args += compiled[1]
            continue
        expr = _expression(field)
        if expr is None:
            return None
        if not isinstance(condition, dict):
            condition = {"$eq": condition}
        for op, value in condition.items():
            if op == "$options":
                continue
            if op in ("$eq", "$ne") and value is None:
                clauses.append(f"{expr} IS {'NOT ' if op == '$ne' else ''}NULL")
            elif op in ("$in", "$nin"):
                if not value:
                    clauses.append("1" if op == "$nin" else "0")
                else:
                    # A whole-drive inventory can exceed SQLite's bound-parameter limit.
                    clauses.append(f"({expr} {'NOT IN' if op == '$nin' else 'IN'} (SELECT value FROM json_each(?))"
                                   + (f" OR {expr} IS NULL)" if op == "$nin" else ")"))
                    args.append(json.dumps(value))
            elif op == "$regex":
                clauses.append(f"{expr} REGEXP ?")
                args.append(("(?i)" if "i" in condition.get("$options", "") else "") + value)
            elif op in {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte"}:
                symbol = {"$eq": "=", "$ne": "!=", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
                clauses.append(f"({expr} {symbol} ?" + (f" OR {expr} IS NULL)" if op == "$ne" else ")"))
                args.append(value)
            else:
                return None
    return " AND ".join(clauses) or "1", args


class Cursor:
    def __init__(self, collection: Collection, query: dict[str, Any], projection: dict[str, int] | None = None) -> None:
        self.collection, self.query, self.projection = collection, query, projection
        self.order: list[tuple[str, int]] = []
        self.offset, self.maximum = 0, 0

    def sort(self, key, direction=1):  # type: ignore[no-untyped-def]
        self.order = [(key, direction)] if isinstance(key, str) else key
        return self

    def skip(self, n: int) -> Cursor:
        self.offset = n
        return self

    def limit(self, n: int) -> Cursor:
        self.maximum = n
        return self

    def __iter__(self):  # type: ignore[no-untyped-def]
        store = self.collection.store
        compiled = _where(self.query)
        fast = compiled is not None and all(_expression(k) is not None for k, _ in self.order)
        with store._read_guard():
            sql, args = "SELECT body FROM documents WHERE collection = ?", [self.collection.name]
            if fast:
                sql += " AND " + compiled[0]
                args += compiled[1]
                if self.order:
                    sql += " ORDER BY " + ", ".join(f"{_expression(k)} {'DESC' if d < 0 else 'ASC'}" for k, d in self.order)
                sql += " LIMIT ? OFFSET ?"
                args += [self.maximum or -1, self.offset]
            docs = [json.loads(r[0]) for r in store._reader().execute(sql, args)]
        if not fast:
            docs = [d for d in docs if matches(d, self.query)]
            def order_value(doc: dict[str, Any], key: str) -> tuple:
                value = (_values(doc, key) or [None])[0]
                if value is None:
                    return (0, 0, "")
                if isinstance(value, (int, float)):
                    return (1, 1, value)
                if isinstance(value, str):
                    return (1, 2, value)
                return (1, 3, json.dumps(value, sort_keys=True))
            for key, direction in reversed(self.order):
                docs.sort(key=lambda d: order_value(d, key), reverse=direction < 0)
            docs = docs[self.offset:self.offset + self.maximum if self.maximum else None]
        if self.projection and any(self.projection.values()):
            docs = [{k: v for k, v in d.items() if self.projection.get(k) or (k == "_id" and self.projection.get(k, 1))}
                    for d in docs]
        return iter(docs)


class Collection:
    def __init__(self, store: KnowledgeDB, name: str) -> None:
        self.store, self.name = store, name

    def find(self, query=None, projection=None, *, limit: int = 0, skip: int = 0, sort=None,
             **kwargs) -> Cursor:  # type: ignore[no-untyped-def]
        cursor = Cursor(self, query or {}, projection)
        if sort:
            cursor.sort(sort)
        return cursor.skip(skip).limit(limit)

    def find_one(self, query=None, projection=None, sort=None, **kwargs):  # type: ignore[no-untyped-def]
        cursor = self.find(query, projection)
        if sort:
            cursor.sort(sort)
        return next(iter(cursor.limit(1)), None)

    def count_documents(self, query, limit=0, **kwargs) -> int:  # type: ignore[no-untyped-def]
        compiled = _where(query)
        if compiled is None:
            return len(list(self.find(query).limit(limit)))
        with self.store._read_guard():
            sql = "SELECT COUNT(*) FROM (SELECT 1 FROM documents WHERE collection=? AND " + compiled[0]
            sql += " LIMIT ?)"
            return self.store._reader().execute(sql, [self.name, *compiled[1], limit or -1]).fetchone()[0]

    def distinct(self, field: str, query=None) -> list[Any]:  # type: ignore[no-untyped-def]
        values = [v for d in self.find(query) for v in _values(d, field)]
        return list(dict.fromkeys(values))

    def _save(self, doc: dict[str, Any], insert: bool = False) -> None:
        try:
            if insert:
                self.store._writer.execute("INSERT INTO documents(collection,id,body) VALUES(?,?,?)",
                                           (self.name, doc["_id"], json.dumps(doc, ensure_ascii=False)))
            else:
                self.store._writer.execute("INSERT INTO documents(collection,id,body) VALUES(?,?,?) "
                                           "ON CONFLICT(collection,id) DO UPDATE SET body=excluded.body",
                                           (self.name, doc["_id"], json.dumps(doc, ensure_ascii=False)))
        except sqlite3.IntegrityError as exc:
            raise WriteConflict(f"duplicate {self.name} record") from exc

    def insert_one(self, doc, **kwargs):  # type: ignore[no-untyped-def]
        with self.store.transaction():
            self._save(doc, insert=True)
        return SimpleNamespace(inserted_id=doc["_id"])

    def insert_many(self, docs, **kwargs):  # type: ignore[no-untyped-def]
        with self.store.transaction():
            for doc in docs:
                self._save(doc, insert=True)

    def update_one(self, query, changes, upsert=False, **kwargs):  # type: ignore[no-untyped-def]
        with self.store.transaction():
            doc = self.find_one(query)
            if doc is None and not upsert:
                return SimpleNamespace(modified_count=0)
            doc = doc or deepcopy(query)
            for op, values in changes.items():
                for key, value in values.items():
                    if op == "$set" or (op == "$max" and (doc.get(key) is None or doc[key] < value)):
                        doc[key] = value
                    elif op == "$inc":
                        doc[key] = doc.get(key, 0) + value
                    elif op == "$unset":
                        doc.pop(key, None)
            self._save(doc)
        return SimpleNamespace(modified_count=1)

    def update_many(self, query, changes, **kwargs):  # type: ignore[no-untyped-def]
        with self.store.transaction():
            docs = list(self.find(query))
            for doc in docs:
                self.update_one({"_id": doc["_id"]}, changes)
        return SimpleNamespace(modified_count=len(docs))

    def delete_one(self, query, **kwargs):  # type: ignore[no-untyped-def]
        with self.store.transaction():
            doc = self.find_one(query)
            if doc:
                self.store._writer.execute("DELETE FROM documents WHERE collection=? AND id=?", (self.name, doc["_id"]))

    def delete_many(self, query, **kwargs):  # type: ignore[no-untyped-def]
        with self.store.transaction():
            if not query:
                self.store._writer.execute("DELETE FROM documents WHERE collection=?", (self.name,))
            else:
                for doc in self.find(query):
                    self.store._writer.execute("DELETE FROM documents WHERE collection=? AND id=?", (self.name, doc["_id"]))

    def aggregate(self, pipeline):  # type: ignore[no-untyped-def]
        # Only ledger/count projections use this after the domain grouping runs in Python.
        docs = list(self.find())
        for step in pipeline:
            if "$match" in step:
                docs = [d for d in docs if matches(d, step["$match"])]
            elif "$group" in step:
                spec, groups = step["$group"], {}
                for d in docs:
                    key = (_values(d, spec["_id"][1:]) or [None])[0]
                    row = groups.setdefault(key, {"_id": key})
                    for name, expr in spec.items():
                        if name != "_id":
                            if expr != {"$sum": 1}:
                                raise ValueError("unsupported count projection")
                            row[name] = row.get(name, 0) + 1
                docs = list(groups.values())
            else:
                raise ValueError("unsupported record projection")
        return docs


class KnowledgeDB:
    def __init__(self, path: Path) -> None:
        self.path, self.name = path, path.stem
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._write_lock, self._local = threading.RLock(), threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._writer = self._connect()
        self._writer.executescript("CREATE TABLE IF NOT EXISTS documents(collection TEXT NOT NULL,id TEXT NOT NULL,"
                                  "body TEXT NOT NULL,PRIMARY KEY(collection,id));"
                                  "CREATE INDEX IF NOT EXISTS document_path_lookup ON documents(collection,json_extract(body,'$.path'));"
                                  "CREATE INDEX IF NOT EXISTS document_status_lookup ON documents(collection,json_extract(body,'$.status'));"
                                  "CREATE INDEX IF NOT EXISTS document_root_lookup ON documents(collection,json_extract(body,'$.root_id'));"
                                  "CREATE UNIQUE INDEX IF NOT EXISTS document_paths ON documents(collection,json_extract(body,'$.path')) "
                                  "WHERE collection IN ('roots','sources');"
                                  "CREATE UNIQUE INDEX IF NOT EXISTS document_sequences ON documents(collection,json_extract(body,'$.seq')) "
                                  "WHERE collection IN ('events','event_groups');")
        if os.name != "nt":
            path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=30)
        enable_incremental_on_new(conn)  # must precede WAL: switching to WAL writes the file header
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.create_function("regexp", 2, lambda pattern, value: bool(value is not None and re.search(pattern, str(value))))
        self._connections.append(conn)
        return conn

    def _read_guard(self):  # type: ignore[no-untyped-def]
        """Reads inside this thread's transaction use the writer connection, so they hold the
        lock. Other reads use the thread's own WAL reader and see the last committed snapshot
        without waiting: a long scan writing file after file no longer stalls the UI's queries."""
        if getattr(self._local, "transaction", False):
            return self._write_lock
        return nullcontext()

    def _reader(self) -> sqlite3.Connection:
        if getattr(self._local, "transaction", False):
            return self._writer
        if not hasattr(self._local, "reader"):
            self._local.reader = self._connect()
        return self._local.reader

    def __getitem__(self, collection: str) -> Collection:
        return Collection(self, collection)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self._write_lock:
            if getattr(self._local, "transaction", False):
                yield Session()
                return
            self._writer.execute("BEGIN IMMEDIATE")
            self._local.transaction = True
            try:
                yield Session()
                self._writer.execute("COMMIT")
            except BaseException:
                self._writer.execute("ROLLBACK")
                raise
            finally:
                self._local.transaction = False

    def next_seq(self, counter: str, session=None) -> int:  # type: ignore[no-untyped-def]
        with self.transaction():
            self["counters"].update_one({"_id": counter}, {"$inc": {"seq": 1}}, upsert=True)
            return self["counters"].find_one({"_id": counter})["seq"]

    def compact(self) -> None:
        compact(self._writer, self._write_lock, self.path.name)

    def drop(self) -> None:
        with self.transaction():
            self._writer.execute("DELETE FROM documents")

    def close(self) -> None:
        for conn in self._connections:
            conn.close()
        self._connections.clear()
