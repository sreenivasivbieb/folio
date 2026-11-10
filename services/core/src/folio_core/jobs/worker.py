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

    def __init__(self, queue: JobQueue, handlers: dict[str, Handler], size: int = 2,
                 scan_kinds: tuple[str, ...] = ("scan_root",)) -> None:
        self.queue = queue
        self.handlers = handlers
        self.size = max(1, size)
        self.scan_kinds = scan_kinds
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self.queue.recover()
        # One dedicated lane walks folders; the content workers never pick up scans. Walking a
        # whole drive can take minutes, and indexing must keep moving while it does.
        lanes: list[tuple[str, tuple[str, ...] | None, tuple[str, ...]]] = [("scan", self.scan_kinds, ())]
        lanes += [(f"worker-{i}", None, self.scan_kinds) for i in range(self.size)]
        for name, kinds, exclude in lanes:
            t = threading.Thread(target=self._loop, args=(kinds, exclude), name=f"folio-{name}", daemon=True)
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

    def _loop(self, kinds: tuple[str, ...] | None = None, exclude: tuple[str, ...] = ()) -> None:
        while not self._stop.is_set():
            try:
                job = self.queue.claim(kinds, exclude)
            except Exception:  # e.g. a locked database: back off instead of killing the worker
                log.exception("could not claim a job")
                self._stop.wait(2.0)
                continue
            if job is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        handler = self.handlers.get(job.kind)
        if handler is None:
            self.queue.fail(job.id, f"no handler for job kind {job.kind!r}", permanent=True)
            return
        try:
            message = handler(job)
            self.queue.finish(job.id, message)
        except Exception as exc:  # the cause is stored and shown in the job dashboard
            log.warning("job %s (%s) failed: %s", job.id, job.kind, exc)
            detail: Any = getattr(exc, "user_message", None) or f"{type(exc).__name__}: {exc}"
            try:
                self.queue.fail(job.id, f"{detail}\n\n{traceback.format_exc(limit=5)}")
            except Exception:  # never let bookkeeping kill the worker thread; recover() re-queues it
                log.exception("could not record failure of job %s", job.id)
