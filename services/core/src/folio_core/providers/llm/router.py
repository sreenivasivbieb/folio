"""Bring-your-own-key LLM routing.

The project chooses a provider preset (or any OpenAI-compatible base URL), a model, and — for
hosted providers — supplies its own API key. Configuration lives in the knowledge store's
``settings`` (``llm.config``); the key lives in the secret store. ``ConfiguredLLM`` reads the
current configuration on every call, so changes in the UI apply without a restart.
"""

from __future__ import annotations

import threading
from typing import Any

from pydantic import BaseModel

from ...domain.errors import Unavailable
from ...store import repo
from ...store.local import KnowledgeDB
from ..secrets import SecretStore
from .openai_compat import OpenAICompatibleLLM, is_loopback


class Preset(BaseModel):
    id: str
    label: str
    base_url: str
    needs_key: bool
    key_url: str | None = None
    suggested_models: list[str] = []


# Model names are only suggestions; the UI lists the provider's live catalogue via /models.
PRESETS: dict[str, Preset] = {p.id: p for p in [
    Preset(id="openrouter", label="OpenRouter", base_url="https://openrouter.ai/api/v1", needs_key=True,
           key_url="https://openrouter.ai/keys",
           suggested_models=["openai/gpt-4o-mini", "qwen/qwen-2.5-72b-instruct", "meta-llama/llama-3.3-70b-instruct"]),
    Preset(id="openai", label="OpenAI", base_url="https://api.openai.com/v1", needs_key=True,
           key_url="https://platform.openai.com/api-keys", suggested_models=["gpt-4o-mini", "gpt-4.1-mini"]),
    Preset(id="qwen", label="Qwen (Alibaba Cloud)", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
           needs_key=True, key_url="https://modelstudio.console.alibabacloud.com/",
           suggested_models=["qwen-plus", "qwen-turbo", "qwen-max"]),
    Preset(id="groq", label="Groq", base_url="https://api.groq.com/openai/v1", needs_key=True,
           key_url="https://console.groq.com/keys", suggested_models=["llama-3.3-70b-versatile"]),
    Preset(id="ollama", label="Ollama (on this computer)", base_url="http://127.0.0.1:11434/v1", needs_key=False,
           key_url="https://ollama.com/download", suggested_models=["qwen2.5:3b", "qwen2.5:7b"]),
    Preset(id="custom", label="Custom OpenAI-compatible", base_url="", needs_key=False),
]}


class LLMConfig(BaseModel):
    provider: str
    base_url: str
    model: str


def key_name(provider: str) -> str:
    return f"llm.{provider}.api_key"


class ConfiguredLLM:
    """The project's LLM, or ``configured == False`` when none is set (rules are used then)."""

    def __init__(self, kdb: KnowledgeDB, secrets: SecretStore) -> None:
        self.kdb = kdb
        self.secrets = secrets
        self._cache: tuple[tuple[str, str, str | None], OpenAICompatibleLLM] | None = None
        self._lock = threading.Lock()

    def config(self) -> LLMConfig | None:
        raw = repo.get_setting(self.kdb, "llm.config")
        return LLMConfig.model_validate(raw) if raw else None

    def client(self) -> OpenAICompatibleLLM | None:
        cfg = self.config()
        if cfg is None or not cfg.base_url or not cfg.model:
            return None
        key = self.secrets.get(key_name(cfg.provider))
        if cfg.provider in PRESETS and PRESETS[cfg.provider].needs_key and not key:
            return None  # e.g. the key was removed: not usable, so the offline rules take over
        ident = (cfg.base_url, cfg.model, key)
        with self._lock:
            if self._cache is None or self._cache[0] != ident:
                label = PRESETS[cfg.provider].label.split(" ")[0].lower() if cfg.provider in PRESETS else "custom"
                old = self._cache[1] if self._cache else None
                self._cache = (ident, OpenAICompatibleLLM(cfg.base_url, cfg.model, key, label=label))
                if old is not None:
                    old.close()  # do not leak the previous HTTP connection pool
            return self._cache[1]

    @property
    def configured(self) -> bool:
        return self.client() is not None

    @property
    def model_id(self) -> str:
        c = self.client()
        return c.model_id if c else "none"

    @property
    def is_local(self) -> bool:
        cfg = self.config()
        return cfg is None or is_loopback(cfg.base_url)

    def complete_json(self, system: str, user: str, json_schema: dict[str, Any]) -> str:
        c = self.client()
        if c is None:
            raise Unavailable("no LLM configured — add one in Settings")
        return c.complete_json(system, user, json_schema)
