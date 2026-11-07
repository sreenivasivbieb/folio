from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any

from .queue import Job, JobQueue

log = logging.getLogger(__name__)

Handler = Callable[[Job], str | None]


class WorkerPool:
    """N daemon threads pulling from the queue. Indexing never runs on the request thread, so
    the UI stays responsive while files are processed (NFR: responsiveness)."""

    def __init__(self, queue: JobQueue, handlers: dict[str, Handler], size: int = 2) -> None:
        self.queue = queue
        self.handlers = handlers
        self.size = size
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self.queue.recover()
        for i in range(self.size):
            t = threading.Thread(target=self._loop, name=f"folio-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def notify(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout=5)

    def run_until_idle(self) -> None:
        """Synchronously drain the queue on the calling thread (tests, CLI)."""
        while (job := self.queue.claim()) is not None:
            self._run(job)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.queue.claim()
            if job is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        handler = self.handlers.get(job.kind)
        if handler is None:
            self.queue.fail(job.id, f"no handler for job kind {job.kind!r}")
            return
        try:
            message = handler(job)
            self.queue.finish(job.id, message)
        except Exception as exc:  # the cause is stored and shown in the job dashboard
            log.warning("job %s (%s) failed: %s", job.id, job.kind, exc)
            detail: Any = getattr(exc, "user_message", None) or f"{type(exc).__name__}: {exc}"
            self.queue.fail(job.id, f"{detail}\n\n{traceback.format_exc(limit=5)}")
