"""Speech-to-text through the project's connected AI provider (Groq or OpenAI Whisper APIs).

So voice labels and audio/video indexing work right away with the key the user already gave,
without the 484 MB local model. The local model, once downloaded, always takes priority (it is
offline). Cloud use follows the same opt-in as the LLM (providers/privacy.py).
"""

from __future__ import annotations

import io
import logging
import time
import wave
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np

from ...domain.errors import Unavailable
from .audio import SAMPLE_RATE
from .base import Progress, Segment

log = logging.getLogger(__name__)

# host -> (transcription model, translation model). Only providers with a Whisper-compatible API.
SPEECH_MODELS = {
    "api.groq.com": ("whisper-large-v3-turbo", "whisper-large-v3"),
    "api.openai.com": ("whisper-1", "whisper-1"),
}
CHUNK_S = 8 * 60  # 8 min of 16 kHz 16-bit mono ≈ 15 MB: under the providers' 25 MB upload limit


def _wav_bytes(samples: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _is_speech(seg: dict[str, Any]) -> bool:
    """Whisper answers silence or noise with "." or similar: keep only real words."""
    text = str(seg.get("text", "")).strip()
    if not any(ch.isalnum() for ch in text):
        return False
    return float(seg.get("no_speech_prob") or 0) < 0.6


class CloudWhisper:
    size_mb = 0
    attempts = 5  # free tiers rate-limit audio (e.g. a few requests per minute): wait and retry

    def _post(self, client: Any, path: str, form: dict[str, str], data: bytes) -> Any:
        from ..llm.openai_compat import retry_after

        delay = 3.0
        for attempt in range(self.attempts):
            try:
                resp = client._client.post(f"{client.base_url}/{path}", data=form,
                                           files={"file": ("audio.wav", data, "audio/wav")})
            except Exception as exc:
                if attempt == self.attempts - 1:
                    raise Unavailable(f"could not reach the speech service: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.attempts - 1:
                wait = min(retry_after(resp.headers.get("retry-after"), delay), 60)
                log.info("speech service busy (HTTP %s); retrying in %.0fs", resp.status_code, wait)
                time.sleep(wait)
                delay *= 2
                continue
            return resp
        return resp

    def __init__(self, llm: Any) -> None:  # ConfiguredLLM
        self.llm = llm

    def _endpoint(self) -> tuple[Any, tuple[str, str]] | None:
        client = self.llm.client() if self.llm is not None else None
        if client is None:
            return None
        models = SPEECH_MODELS.get(urlparse(client.base_url).hostname or "")
        return (client, models) if models else None

    def available(self) -> bool:
        return self._endpoint() is not None

    @property
    def model_id(self) -> str:
        ep = self._endpoint()
        return f"{urlparse(ep[0].base_url).hostname}:{ep[1][0]}" if ep else "none"

    def transcribe(self, audio: Path | np.ndarray, language: str | None = None, prompt: str | None = None,
                   on_progress: Progress | None = None, task: str = "transcribe",
                   beam_size: int = 5) -> list[Segment]:
        ep = self._endpoint()
        if ep is None:
            raise Unavailable("the connected AI provider has no speech-to-text API")
        client, (transcribe_model, translate_model) = ep
        model = translate_model if task == "translate" else transcribe_model
        path = "audio/translations" if task == "translate" else "audio/transcriptions"
        if isinstance(audio, Path):
            pieces = [(0.0, audio.read_bytes())]
        else:
            step = CHUNK_S * SAMPLE_RATE
            pieces = [(i / SAMPLE_RATE, _wav_bytes(audio[i:i + step])) for i in range(0, max(audio.size, 1), step)]
        out: list[Segment] = []
        for n, (offset, data) in enumerate(pieces):
            form = {"model": model, "response_format": "verbose_json", "temperature": "0"}
            if prompt:
                form["prompt"] = prompt[:800]
            if language and task != "translate":
                form["language"] = language
            resp = self._post(client, path, form, data)
            if resp.status_code >= 400:
                raise Unavailable(f"speech service returned HTTP {resp.status_code}: {resp.text[:200]}")
            body = resp.json()
            segments = body.get("segments") or []
            if segments:
                out += [Segment(start=offset + float(s.get("start", 0)), end=offset + float(s.get("end", 0)),
                                text=str(s.get("text", "")).strip()) for s in segments if _is_speech(s)]
            elif _is_speech(body):
                out.append(Segment(start=offset, end=offset + float(body.get("duration") or 0), text=body["text"].strip()))
            if on_progress:
                on_progress((n + 1) / len(pieces))
        return out


class HybridTranscriber:
    """Local Whisper when downloaded (offline); otherwise the connected provider's speech API."""

    def __init__(self, local: Any, cloud: CloudWhisper) -> None:
        self.local = local
        self.cloud = cloud
        self.size_mb = getattr(local, "size_mb", 0)

    def _local_ready(self) -> bool:
        try:
            return bool(self.local is not None and self.local.installed())
        except Exception:
            return False

    def _active(self) -> Any:
        if self._local_ready():
            return self.local
        if self.cloud.available():
            return self.cloud
        return self.local

    @property
    def model_id(self) -> str:
        active = self._active()
        return active.model_id if active is not None else "none"

    @property
    def is_local(self) -> bool:
        return self._active() is not self.cloud

    def installed(self) -> bool:
        return self._local_ready() or self.cloud.available()

    def local_installed(self) -> bool:
        return self._local_ready()

    def transcribe(self, audio: Path | np.ndarray, **kw: Any) -> list[Segment]:
        active = self._active()
        if active is None or (active is self.local and not self._local_ready()):
            raise Unavailable("speech is not set up — connect Groq/OpenAI in Settings → AI model, "
                              "or download the offline speech model in Settings → Voice")
        return active.transcribe(audio, **kw)

    # The explicit download job and warm-up only concern the local model.
    def download(self, *a: Any, **kw: Any) -> None:
        if self.local is None or not hasattr(self.local, "download"):
            raise Unavailable("offline speech is not available in this build")
        self.local.download(*a, **kw)

    def warm(self) -> None:
        if self._local_ready() and hasattr(self.local, "warm"):
            self.local.warm()
