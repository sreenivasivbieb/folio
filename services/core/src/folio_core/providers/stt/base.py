from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Segment:
    start: float  # seconds
    end: float
    text: str


class Transcriber(Protocol):
    """Speech-to-text. Used in two modes: short voice commands and long media files."""

    model_id: str
    is_local: bool

    def transcribe(
        self, audio_path: Path, language: str | None = None, prompt: str | None = None
    ) -> list[Segment]:
        """``prompt`` carries the personal vocabulary (verified names) to bias recognition."""
        ...
