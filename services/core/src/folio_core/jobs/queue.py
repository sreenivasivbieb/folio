from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import BaseModel

from ..domain.ids import new_id
from ..realtime import Bus
from ..store.db import Database, dumps, loads, utcnow


class Job(BaseModel):
    id: str
    kind: str
    payload: dict[str, Any]
    status: str
    priority: int
    attempts: int
    max_attempts: int
    progress: float
    message: str | None
    error: str | None
    created_at: str
    updated_at: str


def _job(r: sqlite3.Row) -> Job:
    return Job(**{**dict(r), "payload": loads(r["payload"])})


class JobQueue:
    def __init__(self, db: Database, bus: Bus) -> None:
        self.db = db
        self.bus = bus

    def enqueue(self, kind: str, payload: dict[str, Any], *, dedupe_key: str | None = None,
                priority: int = 0, max_attempts: int = 2) -> str | None:
        """Queue a job. Returns its id, or None if an identical job is already active."""
        now = utcnow()
        job_id = new_id("job")
        with self.db.write() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO ix.jobs(id, kind, payload, status, priority, max_attempts, "
                "dedupe_key, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
                (job_id, kind, dumps(payload), priority, max_attempts, dedupe_key, now, now),
            )
        if cur.rowcount == 0:
            return None
        self._publish(job_id)
        return job_id

    def claim(self) -> Job | None:
        with self.db.write() as conn:
            r = conn.execute(
                "UPDATE ix.jobs SET status = 'running', attempts = attempts + 1, updated_at = ? "
                "WHERE id = (SELECT id FROM ix.jobs WHERE status = 'queued' "
                "            ORDER BY priority DESC, created_at LIMIT 1) RETURNING *",
                (utcnow(),),
            ).fetchone()
        if r is None:
            return None
        job = _job(r)
        self._publish(job.id)
        return job

    def progress(self, job_id: str, progress: float, message: str | None = None) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE ix.jobs SET progress = ?, message = ?, updated_at = ? WHERE id = ?",
                (progress, message, utcnow(), job_id),
            )
        self._publish(job_id)

    def finish(self, job_id: str, message: str | None = None) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE ix.jobs SET status = 'done', progress = 1, message = ?, error = NULL, "
                "updated_at = ? WHERE id = ?",
                (message, utcnow(), job_id),
            )
        self._publish(job_id)

    def fail(self, job_id: str, error: str) -> None:
        """Retry while attempts remain; otherwise mark failed with the cause (shown in the UI)."""
        with self.db.write() as conn:
            conn.execute(
                "UPDATE ix.jobs SET status = CASE WHEN attempts < max_attempts THEN 'queued' "
                "ELSE 'failed' END, error = ?, updated_at = ? WHERE id = ?",
                (error[-4000:], utcnow(), job_id),
            )
        self._publish(job_id)

    def retry(self, job_id: str) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE ix.jobs SET status = 'queued', attempts = 0, error = NULL, updated_at = ? "
                "WHERE id = ? AND status IN ('failed', 'cancelled')",
                (utcnow(), job_id),
            )
        self._publish(job_id)

    def recover(self) -> int:
        """Re-queue jobs interrupted by a crash or forced kill (NFR: reliability)."""
        with self.db.write() as conn:
            cur = conn.execute(
                "UPDATE ix.jobs SET status = 'queued', updated_at = ? WHERE status = 'running'",
                (utcnow(),),
            )
        return cur.rowcount

    def get(self, job_id: str) -> Job | None:
        r = self.db.reader().execute("SELECT * FROM ix.jobs WHERE id = ?", (job_id,)).fetchone()
        return _job(r) if r else None

    def list(self, status: str | None = None, limit: int = 100) -> list[Job]:
        conn = self.db.reader()
        if status:
            rows = conn.execute(
                "SELECT * FROM ix.jobs WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = conn.execute("SELECT * FROM ix.jobs ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [_job(r) for r in rows]

    def counts(self) -> dict[str, int]:
        rows = self.db.reader().execute("SELECT status, COUNT(*) FROM ix.jobs GROUP BY status")
        return {r[0]: r[1] for r in rows}

    def pending(self) -> int:
        r = self.db.reader().execute(
            "SELECT COUNT(*) FROM ix.jobs WHERE status IN ('queued', 'running')"
        ).fetchone()
        return int(r[0])

    def _publish(self, job_id: str) -> None:
        job = self.get(job_id)
        if job:
            self.bus.publish({"type": "job", "job": job.model_dump()})
