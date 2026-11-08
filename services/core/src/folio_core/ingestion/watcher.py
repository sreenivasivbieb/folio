"""Folder watching (FR-1). Runs in the core service (ADR-0003): the core owns sources and
content hashes, so the shell does not have to relay file events across processes.

Events are debounced per path; a full rescan on startup catches changes made while the app was
closed. Re-indexing is cheap when nothing changed because of the content-hash check.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .service import IngestionService

log = logging.getLogger(__name__)

DEBOUNCE_S = 1.5


class FolderWatcher:
    def __init__(self, ingestion: IngestionService) -> None:
        self.ingestion = ingestion
        self._observer = None
        self._pending: dict[Path, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._flusher: threading.Thread | None = None
        self._watched: dict[str, object] = {}  # root path -> watchdog ObservedWatch

    def start(self) -> None:
        try:
            from watchdog.observers import Observer
        except ImportError:  # pragma: no cover
            log.warning("watchdog not installed; folder watching disabled")
            return
        self._observer = Observer()
        self._observer.start()
        self.sync()
        self._flusher = threading.Thread(target=self._flush_loop, name="folio-watch", daemon=True)
        self._flusher.start()

    def sync(self) -> None:
        """(Re)schedule watches to match the roots table."""
        if self._observer is None:
            return
        from watchdog.events import FileSystemEventHandler

        watcher = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):  # type: ignore[no-untyped-def]
                if event.is_directory:
                    return
                for attr in ("src_path", "dest_path"):
                    p = getattr(event, attr, None)
                    if p:
                        watcher._queue(Path(p if isinstance(p, str) else p.decode()))

        wanted = {r.path: r for r in self.ingestion.roots() if r.watch}
        for path in list(self._watched):
            if path not in wanted:  # root removed: stop watching it
                self._observer.unschedule(self._watched.pop(path))
        for path, root in wanted.items():
            if path in self._watched:
                continue
            target = Path(path)
            watch_dir = target if root.kind == "folder" else target.parent
            if not watch_dir.exists():
                continue
            self._watched[path] = self._observer.schedule(Handler(), str(watch_dir), recursive=root.kind == "folder")

    def _queue(self, path: Path) -> None:
        with self._lock:
            self._pending[path] = time.monotonic()

    def _flush_loop(self) -> None:
        while not self._stop.wait(0.5):
            now = time.monotonic()
            with self._lock:
                ready = [p for p, t in self._pending.items() if now - t >= DEBOUNCE_S]
                for p in ready:
                    del self._pending[p]
            for p in ready:
                try:
                    self.ingestion.scan_path(p)
                except Exception as exc:
                    log.warning("watch event for %s failed: %s", p, exc)

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
