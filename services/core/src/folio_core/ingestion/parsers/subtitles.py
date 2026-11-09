from __future__ import annotations

import re
from pathlib import Path

from ...domain.models import SourceKind
from ..base import ParseContext, ParsedUnit
from .text import read_text

_TS = re.compile(
    r"(?P<a>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<b>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
_TAGS = re.compile(r"<[^>]+>")


def parse_timestamp(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return hours * 3600 + minutes * 60 + seconds


class SubtitleParser:
    """WebVTT and SRT transcripts: one unit per cue with its time range."""

    name = "subtitle"
    extensions = {".vtt": SourceKind.SUBTITLE, ".srt": SourceKind.SUBTITLE}
    sandboxed = True
    # Plain-text reading has no native code: small files parse in-process. Launching a sandbox
    # child costs ~2 s in the packaged app, which made a few thousand notes take an hour.
    inprocess_max_bytes = 8 << 20

    def parse(self, path: Path, ctx: ParseContext) -> list[ParsedUnit]:
        units: list[ParsedUnit] = []
        for block in re.split(r"\r?\n\s*\r?\n", read_text(path)):
            lines = [ln for ln in block.strip().splitlines() if ln.strip()]
            for i, line in enumerate(lines):
                m = _TS.search(line)
                if not m:
                    continue
                text = _TAGS.sub("", " ".join(lines[i + 1 :])).strip()
                if text:
                    units.append(ParsedUnit(text, {
                        "kind": "time",
                        "start": parse_timestamp(m["a"]),
                        "end": parse_timestamp(m["b"]),
                    }))
                break
        return units
