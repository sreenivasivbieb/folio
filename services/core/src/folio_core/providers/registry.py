from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import Settings
from ..domain.errors import Unavailable
from .embeddings.base import Embedder
from .embeddings.hashing import HashingEmbedder
from .llm.base import LLMProvider
from .llm.fake import FakeLLM
from .llm.openai_compat import OpenAICompatibleLLM
from .stt.base import Transcriber
from .stt.unavailable import NoTranscriber

log = logging.getLogger(__name__)


@dataclass
class Providers:
    llm: LLMProvider
    embedder: Embedder
    stt: Transcriber


def build_providers(settings: Settings) -> Providers:
    # LLM ---------------------------------------------------------------------------------------
    llm: LLMProvider
    if settings.llm == "openai":
        llm = OpenAICompatibleLLM(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
    else:
        llm = FakeLLM()

    # Embeddings --------------------------------------------------------------------------------
    embedder: Embedder = HashingEmbedder()
    if settings.embedder == "fastembed":
        from .embeddings.fastembed_embedder import FastEmbedEmbedder

        embedder = FastEmbedEmbedder(settings.embed_model, str(settings.data_dir / "models"))

    # Speech-to-text ----------------------------------------------------------------------------
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

    return Providers(llm=llm, embedder=embedder, stt=stt)
