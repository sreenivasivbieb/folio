from __future__ import annotations

from pathlib import Path

from ...domain.models import SourceKind
from ..base import ParseContext, ParsedUnit


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-16", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def paragraphs_with_lines(text: str) -> list[ParsedUnit]:
    """Split on blank lines; each paragraph keeps its 1-based line range."""
    units: list[ParsedUnit] = []
    buf: list[str] = []
    start = 0
    lines = text.splitlines()
    for i, line in enumerate(lines + [""], start=1):
        if line.strip():
            if not buf:
                start = i
            buf.append(line)
        elif buf:
            units.append(ParsedUnit("\n".join(buf).strip(),
                                    {"kind": "text", "line_start": start, "line_end": i - 1}))
            buf = []
    return units


class TextParser:
    name = "text"
    extensions = {
        ".txt": SourceKind.TEXT,
        ".md": SourceKind.MARKDOWN,
        ".markdown": SourceKind.MARKDOWN,
    }
    sandboxed = True

    def parse(self, path: Path, ctx: ParseContext) -> list[ParsedUnit]:
        return paragraphs_with_lines(read_text(path))
