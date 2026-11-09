from __future__ import annotations

import tempfile
from pathlib import Path

from ...domain.errors import Unavailable
from ...domain.models import SourceKind
from ...providers.stt.audio import SAMPLE_RATE, decode_untrusted
from ..base import ParseContext, ParsedUnit

AUDIO = (".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac", ".wma")
VIDEO = (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".wmv")


class MediaParser:
    """Audio and video: the audio track is decoded (PyAV, in a resource-limited child process —
    no system ffmpeg needed on Linux or Windows) and transcribed in batch with timestamps.

    ``ctx.extra["progress"]`` (fraction, message) is called as transcription advances, so a
    20-minute video shows real progress instead of looking stuck."""

    name = "media"
    extensions = {**{e: SourceKind.AUDIO for e in AUDIO}, **{e: SourceKind.VIDEO for e in VIDEO}}
    sandboxed = False  # needs the loaded speech model; decoding itself is sandboxed below

    def parse(self, path: Path, ctx: ParseContext) -> list[ParsedUnit]:
        stt = ctx.transcriber
        if stt is None or not stt.installed():
            raise Unavailable("speech model not downloaded — download it in Settings → Voice to index audio/video")
        report = ctx.extra.get("progress") or (lambda f, m: None)
        report(0.02, "decoding audio")
        with tempfile.TemporaryDirectory() as tmp:
            audio = decode_untrusted(path, Path(tmp) / "audio.npy", ctx.extra.get("timeout_s", 1800),
                                     ctx.extra.get("memory_mb", 4096))
        minutes = audio.size / SAMPLE_RATE / 60
        report(0.05, f"transcribing {minutes:.0f} min of audio")
        segments = stt.transcribe(
            audio, prompt=ctx.vocabulary_prompt,
            on_progress=lambda f: report(0.05 + 0.9 * f, f"transcribing {round(f * 100)}%"),
        )
        return [
            ParsedUnit(s.text, {"kind": "time", "start": round(s.start, 2), "end": round(s.end, 2)})
            for s in segments if s.text
        ]
