from __future__ import annotations

import json
import re
import time
from datetime import UTC
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

    RATE_LIMIT_ATTEMPTS = 8  # free tiers (e.g. Groq: a few thousand tokens per minute) need patience
    SERVER_ATTEMPTS = 4

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        delay = 2.0
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._client.post(f"{self.base_url}/chat/completions", json=body)
            except httpx.TransportError as exc:
                if attempt >= self.SERVER_ATTEMPTS:
                    raise Unavailable(f"cannot reach {self.base_url}: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue
            limited = resp.status_code == 429
            budget = self.RATE_LIMIT_ATTEMPTS if limited else self.SERVER_ATTEMPTS
            if (limited or resp.status_code in (500, 502, 503, 504)) and attempt < budget:
                wait = retry_after(resp.headers.get("retry-after"), 0) or _suggested_wait(resp) or delay
                time.sleep(min(wait + 0.5, 60))
                delay = min(delay * 2, 60)
                continue
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


def retry_after(header: str | None, default: float) -> float:
    """Seconds to wait from a Retry-After header: delay-seconds or an HTTP-date (RFC 9110)."""
    if not header:
        return default
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        from datetime import datetime
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(header)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, IndexError, OverflowError):
        return default


def _suggested_wait(resp: httpx.Response) -> float:
    """Providers often say how long to wait in the message: 'Please try again in 7.66s' / '450ms' / '1m2s'."""
    m = re.search(r"try again in\s+(?:(\d+)m)?(?:([\d.]+)s)?(?:([\d.]+)ms)?", resp.text or "", re.I)
    if not m or not any(m.groups()):
        return 0.0
    minutes, seconds, millis = (float(g) if g else 0.0 for g in m.groups())
    return minutes * 60 + seconds + millis / 1000
