"""Privacy gate: local processing by default, cloud only with a per-project opt-in (NFR: privacy).

Every service calls :func:`ensure_allowed` before handing user content to a provider. A provider
with ``is_local = False`` is refused unless ``cloud.enabled`` is set in the project's settings.
"""

from __future__ import annotations

from typing import Any

from ..domain.errors import PrivacyBlocked
from ..store.local import KnowledgeDB
from ..store.repo import get_setting


def cloud_enabled(kdb: KnowledgeDB) -> bool:
    return bool(get_setting(kdb, "cloud.enabled", False))


def ensure_allowed(kdb: KnowledgeDB, provider: Any) -> None:
    if provider is None or getattr(provider, "is_local", True):
        return
    if not cloud_enabled(kdb):
        raise PrivacyBlocked(
            f"{provider.model_id} is a cloud provider; enable cloud for this project to use it"
        )
