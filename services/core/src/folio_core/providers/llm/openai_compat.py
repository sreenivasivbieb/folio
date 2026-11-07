from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class OpenAICompatibleLLM:
    """Any ``/v1/chat/completions`` endpoint: Ollama, llama.cpp server, vLLM or a cloud vendor.

    ``is_local`` is derived from the URL; a non-loopback endpoint counts as *cloud* and is blocked
    unless the project has opted in (see providers/privacy.py).
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 timeout_s: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model
        self.is_local = (urlparse(base_url).hostname or "") in _LOOPBACK
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    def complete_json(self, system: str, user: str, json_schema: dict[str, Any]) -> str:
        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model_id,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "extraction", "schema": json_schema, "strict": True},
                },
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
