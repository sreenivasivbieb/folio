"""Process-level configuration, read from ``FOLIO_*`` environment variables or CLI flags.

Per-project choices made in the UI (cloud opt-in, LLM provider, type hints) live in the
``settings`` collection of the knowledge store instead, so they travel with the project's data.
API keys live in ``<data_dir>/secrets.json`` (mode 0600) — never in the database or exports.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "folio"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    host: str = "127.0.0.1"  # never bind to a public interface
    port: int = 0  # 0 = pick a random free port
    token: str | None = None  # per-session token; generated if not given
    allowed_origins: tuple[str, ...] = (
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",  # Vite dev server
        "http://127.0.0.1:1420",
    )

    # Providers (see providers/registry.py). The LLM is configured per project in the UI
    # (bring your own key); without one, the offline rule extractor is used.
    embedder: str = "hashing"  # hashing | fastembed
    embed_model: str = "BAAI/bge-small-en-v1.5"
    stt: str = "auto"  # auto | faster-whisper | none
    stt_model: str = "small"  # multilingual: covers Hindi/English mixed speech

    # Jobs and sandboxing.
    workers: int = 2
    parse_timeout_s: int = 180
    parse_memory_mb: int = 2048
    watch: bool = True

    @property
    def secrets_file(self) -> Path:
        return self.data_dir / "secrets.json"

    @property
    def index_db(self) -> Path:
        return self.data_dir / "index.db"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "labels"

    @property
    def runtime_file(self) -> Path:
        """port + token for local CLIs (e.g. a Hyprland push-to-talk binding). Mode 0600."""
        return self.data_dir / "runtime.json"

    @classmethod
    def from_env(cls, **overrides: object) -> Settings:
        env = os.environ
        s = cls()
        mapping: dict[str, object] = {}
        if v := env.get("FOLIO_DATA_DIR"):
            mapping["data_dir"] = Path(v)
        for key in ("token", "embedder", "embed_model", "stt", "stt_model"):
            if v := env.get(f"FOLIO_{key.upper()}"):
                mapping[key] = v
        for key in ("port", "workers", "parse_timeout_s", "parse_memory_mb"):
            if v := env.get(f"FOLIO_{key.upper()}"):
                mapping[key] = int(v)
        if v := env.get("FOLIO_WATCH"):
            mapping["watch"] = v not in ("0", "false", "no")
        if v := env.get("FOLIO_ALLOWED_ORIGINS"):
            mapping["allowed_origins"] = tuple(o.strip() for o in v.split(",") if o.strip())
        mapping.update({k: v for k, v in overrides.items() if v is not None})
        return replace(s, **mapping)  # type: ignore[arg-type]
