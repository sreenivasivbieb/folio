"""SQLite access: two files, one logical database.

* ``knowledge.db`` (schema ``main``): durable user knowledge + the event ledger.
* ``index.db``     (schema ``ix``):   disposable chunks, FTS, vectors, cache and jobs.

Concurrency model: **one writer**. All writes go through :meth:`Database.write`, which holds a
process-wide lock and runs ``BEGIN IMMEDIATE``. Parsers run in subprocesses but only *return*
data; this process is the only one that writes, so there is never ``SQLITE_BUSY`` contention.
Reads use one connection per thread and run concurrently thanks to WAL mode.
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


class Database:
    def __init__(self, knowledge_path: Path, index_path: Path) -> None:
        self.knowledge_path = knowledge_path
        self.index_path = index_path
        knowledge_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._local = threading.local()
        self._writer = self._connect()
        self.has_vec = _load_vec(self._writer)
        self._migrate()

    # --- connections ----------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.knowledge_path, check_same_thread=False, isolation_level=None, timeout=30
        )
        conn.row_factory = sqlite3.Row
        conn.execute("ATTACH DATABASE ? AS ix", (str(self.index_path),))
        for schema in ("main", "ix"):
            conn.execute(f"PRAGMA {schema}.journal_mode=WAL")
            conn.execute(f"PRAGMA {schema}.synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def reader(self) -> sqlite3.Connection:
        """A per-thread read connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            if self.has_vec:
                _load_vec(conn)
            self._local.conn = conn
        return conn

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

    # --- migrations -----------------------------------------------------------------------

    def _migrate(self) -> None:
        for schema, folder in (("main", "knowledge"), ("ix", "index")):
            current = self._writer.execute(f"PRAGMA {schema}.user_version").fetchone()[0]
            files = sorted(
                (f for f in resources.files("folio_core.store").joinpath("migrations", folder).iterdir()
                 if f.name.endswith(".sql")),
                key=lambda f: f.name,
            )
            for f in files:
                version = int(f.name.split("_", 1)[0])
                if version <= current:
                    continue
                log.info("applying %s migration %s", folder, f.name)
                with self._write_lock:
                    self._writer.executescript(f"BEGIN;\n{f.read_text()}\nPRAGMA {schema}.user_version={version};\nCOMMIT;")

    def reset_index(self) -> None:
        """Drop all derived data (index.db) and recreate it empty. User knowledge is untouched."""
        with self._write_lock:
            self._writer.execute("DETACH DATABASE ix")
            for suffix in ("", "-wal", "-shm"):
                Path(str(self.index_path) + suffix).unlink(missing_ok=True)
            self._writer.execute("ATTACH DATABASE ? AS ix", (str(self.index_path),))
            self._writer.execute("PRAGMA ix.journal_mode=WAL")
            self._local = threading.local()  # force readers to reconnect
            self._migrate()

    def close(self) -> None:
        self._writer.close()


# --- small helpers shared by repositories ---------------------------------------------------


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None) -> Any:
    return json.loads(value) if value is not None else None
