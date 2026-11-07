"""Privacy gate: local processing by default, cloud only with a per-project opt-in (NFR: privacy).

Every service calls :func:`ensure_allowed` before handing user content to a provider. A provider
with ``is_local = False`` is refused unless ``cloud.enabled`` is set in the project's settings.
"""

from __future__ import annotations

from typing import Any

from ..domain.errors import PrivacyBlocked
from ..store.db import Database
from ..store.repo import get_setting


def cloud_enabled(db: Database) -> bool:
    return bool(get_setting(db.reader(), "cloud.enabled", False))


def ensure_allowed(db: Database, provider: Any) -> None:
    if getattr(provider, "is_local", True):
        return
    if not cloud_enabled(db):
        raise PrivacyBlocked(
            f"{provider.model_id} is a cloud provider; enable cloud for this project to use it"
        )
