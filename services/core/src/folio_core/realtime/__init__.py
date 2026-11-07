"""In-process pub/sub. Services publish from any thread; the SSE endpoint fans messages out to the
UI so an edit made in one view shows in every view immediately (FR-6), and job progress is live."""

from __future__ import annotations

import asyncio
import threading
from typing import Any


class Bus:
    def __init__(self) -> None:
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subs = [(lp, s) for lp, s in self._subs if s is not q]

    def publish(self, message: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_put, q, message)
            except RuntimeError:  # loop closed
                self.unsubscribe(q)


def _put(q: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
    if q.full():  # slow consumer: drop oldest rather than block producers
        q.get_nowait()
    q.put_nowait(message)
