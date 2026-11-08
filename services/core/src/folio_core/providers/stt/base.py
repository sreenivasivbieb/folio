from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

Progress = Callable[[float], None]  # fraction 0..1


@dataclass(frozen=True)
class Segment:
    start: float  # seconds
    end: float
    text: str


class Transcriber(Protocol):
    """Speech-to-text. Used in two modes: short voice commands and long media files."""

    model_id: str
    is_local: bool

    def installed(self) -> bool:
        """Whether the model files are present locally (no download needed)."""
        ...

    def transcribe(
        self, audio_path: Path, language: str | None = None, prompt: str | None = None,
        on_progress: Progress | None = None,
    ) -> list[Segment]:
        """``prompt`` carries the personal vocabulary (verified names) to bias recognition.
        Never downloads anything: models are fetched only by an explicit download job."""
        ...
