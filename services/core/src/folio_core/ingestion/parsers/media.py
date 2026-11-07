from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ...domain.errors import Unavailable
from ...domain.models import SourceKind
from ..base import ParseContext, ParsedUnit

AUDIO = (".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac")
VIDEO = (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v")


def to_wav16k(src: Path, dst: Path) -> None:
    if shutil.which("ffmpeg") is None:
        raise Unavailable("ffmpeg is not installed")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(dst)],
        check=True, timeout=3600,
    )


class MediaParser:
    """Audio and video: ffmpeg extracts the audio track, the speech model transcribes it in batch
    mode with timestamps. Runs in-process (not sandboxed) because it needs the loaded speech model;
    the untrusted bytes are only ever decoded by the ffmpeg subprocess."""

    name = "media"
    extensions = {**{e: SourceKind.AUDIO for e in AUDIO}, **{e: SourceKind.VIDEO for e in VIDEO}}
    sandboxed = False

    def parse(self, path: Path, ctx: ParseContext) -> list[ParsedUnit]:
        if ctx.transcriber is None:
            raise Unavailable("no speech-to-text model configured")
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "audio.wav"
            to_wav16k(path, wav)
            segments = ctx.transcriber.transcribe(wav, prompt=ctx.vocabulary_prompt)
        return [
            ParsedUnit(s.text, {"kind": "time", "start": round(s.start, 2), "end": round(s.end, 2)})
            for s in segments if s.text
        ]
