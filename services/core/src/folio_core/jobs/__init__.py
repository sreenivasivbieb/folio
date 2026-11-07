"""Background work: a SQLite-backed queue (in index.db) and a thread worker pool.

* **Resumable** — jobs left ``running`` by a crash are re-queued on startup.
* **Idempotent** — ``dedupe_key`` stops the same work being queued twice, and handlers re-check
  content hashes so re-running a job on unchanged data is a no-op.
* **Observable** — status, progress and the failure cause are stored and pushed to the UI.
"""

from .queue import Job, JobQueue
from .worker import WorkerPool

__all__ = ["Job", "JobQueue", "WorkerPool"]
