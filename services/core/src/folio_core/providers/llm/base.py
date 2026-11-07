from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    """Anything that can turn a prompt into schema-constrained JSON text.

    Local runtimes (Ollama, llama.cpp server) and cloud vendors all fit behind this one method,
    so swapping providers never touches extraction code.
    """

    model_id: str
    is_local: bool

    def complete_json(self, system: str, user: str, json_schema: dict[str, Any]) -> str: ...
