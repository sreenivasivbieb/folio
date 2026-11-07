"""Merge parser units into retrieval-sized chunks without losing where they came from.

Units are merged only when they are *adjacent in the same place* (same PDF page, consecutive
lines, consecutive media segments), so every chunk still has one precise locator (FR-2).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .base import ParsedUnit

MAX_CHARS = 1200
MAX_MEDIA_SECONDS = 60.0
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ChunkDraft:
    text: str
    locator: dict[str, Any]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def _union(a: list[float] | None, b: list[float] | None) -> list[float] | None:
    if not a or not b:
        return a or b
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _can_merge(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["kind"] != b["kind"]:
        return False
    if a["kind"] == "page":
        return a.get("page") == b.get("page")
    if a["kind"] == "time":
        return (b["end"] - a["start"]) <= MAX_MEDIA_SECONDS
    if a["kind"] == "text":
        return b["line_start"] - a["line_end"] <= 2
    return a["kind"] == "region"


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    if a["kind"] in ("page", "region"):
        out["rect"] = _union(a.get("rect"), b.get("rect"))
    elif a["kind"] == "time":
        out["start"], out["end"] = min(a["start"], b["start"]), max(a["end"], b["end"])
    elif a["kind"] == "text":
        out["line_start"] = min(a["line_start"], b["line_start"])
        out["line_end"] = max(a["line_end"], b["line_end"])
    return out


def _split_long(unit: ParsedUnit, max_chars: int) -> list[ParsedUnit]:
    if len(unit.text) <= max_chars:
        return [unit]
    parts, buf = [], ""
    for sentence in _SENTENCE.split(unit.text):
        while len(sentence) > max_chars:  # a "sentence" with no punctuation
            parts.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if len(buf) + len(sentence) + 1 > max_chars and buf:
            parts.append(buf)
            buf = ""
        buf = f"{buf} {sentence}".strip()
    if buf:
        parts.append(buf)
    return [ParsedUnit(p, dict(unit.locator)) for p in parts]


def chunk_units(units: list[ParsedUnit], max_chars: int = MAX_CHARS) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for unit in (u for raw in units for u in _split_long(raw, max_chars)):
        text = unit.text.strip()
        if not text:
            continue
        if chunks:
            last = chunks[-1]
            if _can_merge(last.locator, unit.locator) and len(last.text) + len(text) + 1 <= max_chars:
                last.text = f"{last.text}\n{text}"
                last.locator = _merge(last.locator, unit.locator)
                continue
        chunks.append(ChunkDraft(text, dict(unit.locator)))
    return chunks
