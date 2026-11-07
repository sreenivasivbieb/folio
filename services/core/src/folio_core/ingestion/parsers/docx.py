from __future__ import annotations

from pathlib import Path

from ...domain.models import SourceKind
from ..base import ParseContext, ParsedUnit


class DocxParser:
    """Word documents. Locator line numbers are paragraph numbers (tables follow body text)."""

    name = "docx"
    extensions = {".docx": SourceKind.DOCX}
    sandboxed = True

    def parse(self, path: Path, ctx: ParseContext) -> list[ParsedUnit]:
        import docx

        doc = docx.Document(str(path))
        units: list[ParsedUnit] = []
        n = 0
        for para in doc.paragraphs:
            n += 1
            if para.text.strip():
                units.append(ParsedUnit(para.text.strip(),
                                        {"kind": "text", "line_start": n, "line_end": n}))
        for table in doc.tables:
            for row in table.rows:
                n += 1
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    units.append(ParsedUnit(" | ".join(dict.fromkeys(cells)),
                                            {"kind": "text", "line_start": n, "line_end": n}))
        return units
