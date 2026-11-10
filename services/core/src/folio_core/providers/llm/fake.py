from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

Responder = Callable[[str, str], str | dict[str, Any]]


class FakeLLM:
    """Deterministic stand-in for a real model (default until a local LLM is configured).

    ``responses`` may be a list (returned in order, last one repeats) or a callable
    ``(system, user) -> str | dict``. Every call is recorded in ``calls`` so tests can assert
    on prompts and on the number of model calls (NFR: unchanged data costs zero calls).
    """

    is_local = True

    def __init__(self, responses: list[str | dict[str, Any]] | Responder | None = None,
                 model_id: str = "fake-llm", configured: bool = False) -> None:
        self.model_id = model_id
        # Consumers gate on ``configured`` (like ConfiguredLLM): pass True to exercise model paths.
        self.configured = configured
        self._responses = responses
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, json_schema: dict[str, Any]) -> str:
        self.calls.append((system, user))
        r = self._responses
        if r is None:
            out: str | dict[str, Any] = {"entities": [], "claims": []}
        elif callable(r):
            out = r(system, user)
        else:
            out = r[min(len(self.calls) - 1, len(r) - 1)]
        return out if isinstance(out, str) else json.dumps(out)
