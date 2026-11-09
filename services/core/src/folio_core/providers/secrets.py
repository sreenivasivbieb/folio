"""API keys, kept out of the database: ``<data_dir>/secrets.json`` with mode 0600.

Keys never enter the knowledge file, the ledger, exports or logs, and the API never returns them (only
whether one is set and its last four characters).
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from ..domain.errors import Unavailable


class SecretStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except ValueError as exc:
            raise Unavailable("The local credentials file is invalid. Restore it from your backup before saving new credentials.") from exc

    def get(self, name: str) -> str | None:
        return self._read().get(name) or None

    def set(self, name: str, value: str | None) -> None:
        self.update({name: value})

    def update(self, changes: dict[str, str | None]) -> None:
        with self._lock:
            data = self._read()
            for name, value in changes.items():
                if value:
                    data[name] = value
                else:
                    data.pop(name, None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
            if sys.platform != "win32":
                self.path.chmod(0o600)

    @staticmethod
    def hint(value: str | None) -> str | None:
        return f"…{value[-4:]}" if value and len(value) > 8 else ("set" if value else None)
