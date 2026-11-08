from __future__ import annotations

from pathlib import Path

from ...domain.errors import Unavailable
from .base import Segment


class NoTranscriber:
    """Used when no speech model is installed. Typed labels still work; media is skipped."""

    model_id = "none"
    is_local = True

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def installed(self) -> bool:
        return False

    def transcribe(self, audio_path: Path, language: str | None = None,
                   prompt: str | None = None, on_progress=None) -> list[Segment]:  # type: ignore[no-untyped-def]
        raise Unavailable(f"speech-to-text unavailable: {self.reason}")
