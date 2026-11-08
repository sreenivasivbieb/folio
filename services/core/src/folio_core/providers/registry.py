from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..domain.errors import Unavailable
from .embeddings.base import Embedder
from .embeddings.hashing import HashingEmbedder
from .stt.base import Transcriber
from .stt.unavailable import NoTranscriber

log = logging.getLogger(__name__)


@dataclass
class Providers:
    embedder: Embedder
    stt: Transcriber
    llm: Any = None  # tests inject a fake; otherwise the container builds ConfiguredLLM (BYOK)


def build_providers(settings: Settings) -> Providers:
    """Embeddings and speech are process-level choices; the LLM is per project (see llm/router.py)."""
    embedder: Embedder = HashingEmbedder()
    if settings.embedder == "fastembed":
        from .embeddings.fastembed_embedder import FastEmbedEmbedder

        embedder = FastEmbedEmbedder(settings.embed_model, str(settings.data_dir / "models"))

    stt: Transcriber
    if settings.stt == "none":
        stt = NoTranscriber("disabled by configuration")
    else:
        try:
            from .stt.faster_whisper_stt import FasterWhisperTranscriber

            stt = FasterWhisperTranscriber(settings.stt_model, str(settings.data_dir / "models"))
        except Unavailable as exc:
            if settings.stt == "faster-whisper":
                raise
            log.info("speech-to-text disabled: %s", exc)
            stt = NoTranscriber(str(exc))
    return Providers(embedder=embedder, stt=stt)
