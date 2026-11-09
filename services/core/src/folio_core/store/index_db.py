"""index.db — the disposable SQLite store: chunks, full-text + vector index, model cache, jobs.

Everything here can be rebuilt from the files plus the local knowledge file, so deleting
the file is always safe. SQLite stays because it gives FTS5 and sqlite-vec in-process with no
server.

Concurrency: **one writer** (process lock + ``BEGIN IMMEDIATE``); reads use a connection per
thread and run concurrently in WAL mode.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _load_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as exc:  # extension loading disabled or wheel missing
        log.info("sqlite-vec unavailable, using numpy vector fallback: %s", exc)
        return False


class IndexDB:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._local = threading.local()
        self._generation = 0  # bumped by reset() so per-thread readers reconnect
        self._writer = self._connect()
        self.has_vec = _load_vec(self._writer)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def reader(self) -> sqlite3.Connection:
        """A per-thread read connection."""
        cached = getattr(self._local, "conn", None)
        if cached is None or cached[0] != self._generation:
            if cached is not None:
                cached[1].close()
            conn = self._connect()
            if self.has_vec:
                _load_vec(conn)
            self._local.conn = (self._generation, conn)
            return conn
        return cached[1]

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction (re-entrant: nested calls join the outer transaction)."""
        with self._write_lock:
            conn = self._writer
            if conn.in_transaction:
                yield conn
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def _migrate(self) -> None:
        current = self._writer.execute("PRAGMA user_version").fetchone()[0]
        folder = resources.files("folio_core.store").joinpath("migrations", "index")
        for f in sorted((f for f in folder.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name):
            version = int(f.name.split("_", 1)[0])
            if version <= current:
                continue
            log.info("applying index migration %s", f.name)
            with self._write_lock:
                self._writer.executescript(f"BEGIN;\n{f.read_text()}\nPRAGMA user_version={version};\nCOMMIT;")

    def reset(self) -> None:
        """Empty every table (same effect as deleting index.db, but safe while open on Windows)."""
        with self.write() as conn:
            for table in ("chunks", "chunk_vectors", "model_cache", "jobs", "extraction_issues",
                          "merge_suggestions", "meta"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
            conn.execute("DROP TABLE IF EXISTS chunk_vec")
        self._generation += 1

    def close(self) -> None:
        self._writer.close()
