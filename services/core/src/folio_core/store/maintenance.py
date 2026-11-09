"""Keep the local SQLite files from growing forever.

SQLite reuses freed pages but never returns them to the OS unless the database uses
auto_vacuum (set before any table exists) or is VACUUMed. index.db is constantly re-chunked and
re-embedded, so its free pages pile up. New files are created INCREMENTAL; at startup each file
releases its free pages, and an older file with a lot of waste is converted once with VACUUM.
"""

from __future__ import annotations

import logging
import sqlite3
import threading

log = logging.getLogger(__name__)

INCREMENTAL = 2
CONVERT_MIN_FREE_PAGES = 2048  # ~8 MB at 4 KiB pages: below this a full VACUUM is not worth it
CONVERT_MIN_FREE_RATIO = 0.2


def enable_incremental_on_new(conn: sqlite3.Connection) -> None:
    """Call first on a new connection (before journal_mode=WAL or any table): it only takes
    effect on a brand-new, empty file and is a harmless no-op on existing ones."""
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")


def compact(conn: sqlite3.Connection, lock: threading.RLock, name: str) -> None:
    """Release free pages. Call when nothing else is writing (startup, before workers)."""
    try:
        with lock:
            mode = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
            free = conn.execute("PRAGMA freelist_count").fetchone()[0]
            pages = conn.execute("PRAGMA page_count").fetchone()[0]
            if not free:
                return
            if mode == INCREMENTAL:
                conn.execute("PRAGMA incremental_vacuum")
                log.info("%s: released %d free pages", name, free)
            elif free >= CONVERT_MIN_FREE_PAGES and free / max(pages, 1) >= CONVERT_MIN_FREE_RATIO:
                log.info("%s: %d of %d pages are free; compacting once and enabling incremental vacuum",
                         name, free, pages)
                conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
                conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:  # never block startup on housekeeping
        log.warning("%s: compaction skipped: %s", name, exc)
