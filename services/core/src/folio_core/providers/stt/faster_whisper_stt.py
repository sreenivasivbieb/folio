from __future__ import annotations

import threading
from pathlib import Path

from ...domain.errors import Unavailable
from .base import Segment


class FasterWhisperTranscriber:
    """Local Whisper on CPU (int8) with Silero voice-activity detection.

    Install with ``folio-core[speech]``. The model downloads on first use and is cached under
    the data dir; after that it runs offline. Multilingual models handle Hindi/English mixes.
    """

    is_local = True

    def __init__(self, model: str = "small", download_root: str | None = None) -> None:
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            raise Unavailable("faster-whisper is not installed (folio-core[speech])") from exc
        self.model_id = f"faster-whisper-{model}"
        self._name = model
        self._root = download_root
        self._model = None
        self._lock = threading.Lock()

    def _load(self):  # type: ignore[no-untyped-def]
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self._name, device="auto", compute_type="int8", download_root=self._root
                )
        return self._model

    def transcribe(
        self, audio_path: Path, language: str | None = None, prompt: str | None = None
    ) -> list[Segment]:
        segments, _info = self._load().transcribe(
            str(audio_path), language=language, initial_prompt=prompt, vad_filter=True,
            beam_size=5,
        )
        return [Segment(start=s.start, end=s.end, text=s.text.strip()) for s in segments]
