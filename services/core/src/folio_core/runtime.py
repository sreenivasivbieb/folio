"""Installed-app startup, private logs, and ownership of a single local core process."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from contextlib import contextmanager

from .config import Settings
from .domain.errors import Unavailable

log = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    folder = settings.data_dir / "logs"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / "core.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3)
    if sys.platform != "win32":
        folder.chmod(0o700)
        path.chmod(0o600)
    logging.basicConfig(level=os.environ.get("FOLIO_LOG", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stderr), handler], force=True)


@contextmanager
def instance_lock(settings: Settings):  # type: ignore[no-untyped-def]
    path = settings.data_dir / "core.lock"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+") as lock:
        try:
            if sys.platform == "win32":
                import msvcrt

                lock.seek(0)
                if not lock.read(1):
                    lock.write("0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise Unavailable("Folio is already running for this data folder. Close its other window or backend first.") from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
