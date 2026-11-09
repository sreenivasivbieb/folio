from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from ...domain.errors import InvalidInput, Unavailable

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def is_loopback(url: str) -> bool:
    return (urlparse(url).hostname or "") in _LOOPBACK


class OpenAICompatibleLLM:
    """Any ``/v1/chat/completions`` endpoint: OpenAI, OpenRouter, Qwen (DashScope), Groq,
    Ollama, llama.cpp, vLLM or a hackathon router.

    Robust to provider differences:
    * tries ``response_format: json_schema``; if the provider refuses it, falls back to
      ``json_object`` with the schema in the prompt; strips ```json fences from replies,
    * retries rate limits (429) and server errors with backoff (honours ``Retry-After``).

    ``is_local`` is derived from the URL; a non-loopback endpoint counts as *cloud* and needs the
    project's opt-in (see providers/privacy.py).
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 timeout_s: float = 180.0, label: str = "",
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.model_id = f"{label or urlparse(base_url).hostname}:{model}"
        self.is_local = is_loopback(base_url)
        headers = {"X-Title": "Folio", "HTTP-Referer": "https://github.com/sreenivasivbieb/folio"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(timeout=timeout_s, headers=headers, transport=transport,
                                    trust_env=not self.is_local)
        self._json_schema_ok = True

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        delay = 2.0
        for attempt in range(4):
            try:
                resp = self._client.post(f"{self.base_url}/chat/completions", json=body)
            except httpx.TransportError as exc:
                if attempt == 3:
                    raise Unavailable(f"cannot reach {self.base_url}: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                wait = float(resp.headers.get("retry-after", delay))
                time.sleep(min(wait, 30))
                delay *= 2
                continue
            return resp
        return resp

    @staticmethod
    def _error(resp: httpx.Response) -> str:
        try:
            err = resp.json().get("error", resp.text)
            return err.get("message", str(err)) if isinstance(err, dict) else str(err)
        except ValueError:
            return resp.text[:300]

    def complete_json(self, system: str, user: str, json_schema: dict[str, Any]) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        body: dict[str, Any] = {"model": self.model, "temperature": 0, "messages": messages}
        if self._json_schema_ok:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "extraction", "schema": json_schema, "strict": False}}
            resp = self._post(body)
            if resp.is_success:
                return self._content(resp)
            if resp.status_code not in (400, 422):
                self._raise(resp)
            # Many providers/models do not support json_schema: fall back below.
        hint = "\n\nReply with JSON only, matching this JSON Schema:\n" + json.dumps(json_schema)
        body["messages"] = [{"role": "system", "content": system + hint}, {"role": "user", "content": user}]
        body["response_format"] = {"type": "json_object"}
        resp = self._post(body)
        if resp.status_code in (400, 422):  # some providers reject json_object too
            body.pop("response_format")
            resp = self._post(body)
        if not resp.is_success:
            self._raise(resp)
        self._json_schema_ok = False  # remember: this provider/model wants the fallback
        return self._content(resp)

    def _raise(self, resp: httpx.Response) -> None:
        msg = self._error(resp)
        if resp.status_code in (401, 403):
            raise InvalidInput(f"the provider rejected the API key ({resp.status_code}): {msg}")
        if resp.status_code == 404:
            raise InvalidInput(f"model '{self.model}' not found at {self.base_url}: {msg}")
        raise Unavailable(f"LLM request failed ({resp.status_code}): {msg}")

    @staticmethod
    def _content(resp: httpx.Response) -> str:
        content = resp.json()["choices"][0]["message"].get("content") or ""
        return _FENCE.sub("", content.strip())

    def list_models(self) -> list[str]:
        try:
            resp = self._client.get(f"{self.base_url}/models", timeout=20)
        except httpx.TransportError as exc:
            raise Unavailable(f"cannot reach {self.base_url} — check the URL, your connection, "
                              "or that the local server (e.g. Ollama) is running") from exc
        if not resp.is_success:
            self._raise(resp)
        data = resp.json()
        items = data.get("data", data if isinstance(data, list) else [])
        return sorted({m["id"] for m in items if isinstance(m, dict) and "id" in m})

    def ping(self) -> str:
        """A tiny real request, so 'Test connection' proves key + model + JSON mode work."""
        out = self.complete_json("Reply with JSON.", 'Return {"ok": true}.',
                                 {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]})
        json.loads(out)
        return out
