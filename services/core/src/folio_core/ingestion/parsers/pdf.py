from __future__ import annotations

import re
import tempfile
from pathlib import Path

from ...domain.models import SourceKind
from ..base import ParseContext, ParsedUnit
from .ocr import group_lines, ocr_lines, tesseract_available

_PARA_SPLIT = re.compile(r"(?:\r?\n\s*){2,}")
OCR_SCALE = 2.0  # render at 144 dpi for OCR


class PdfParser:
    """Text PDFs via pdfium (Apache/BSD licensed); scanned pages fall back to Tesseract OCR.

    Locators are ``{"kind": "page", "page": n, "rect": [x0, y0, x1, y1]}`` in PDF points with a
    top-left origin, which is what the UI's PDF viewer needs to highlight the evidence region.
    """

    name = "pdf"
    extensions = {".pdf": SourceKind.PDF}
    sandboxed = True

    def parse(self, path: Path, ctx: ParseContext) -> list[ParsedUnit]:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        units: list[ParsedUnit] = []
        try:
            for index in range(len(pdf)):
                page = pdf[index]
                _width, height = page.get_size()
                textpage = page.get_textpage()
                text = textpage.get_text_range()
                if text.strip():
                    units += self._text_units(text, textpage, index + 1, height)
                elif tesseract_available():
                    units += self._ocr_units(page, index + 1)
                textpage.close()
                page.close()
        finally:
            pdf.close()
        return units

    def _text_units(self, text: str, textpage, page_no: int, height: float) -> list[ParsedUnit]:  # type: ignore[no-untyped-def]
        units = []
        pos = 0
        n_chars = textpage.count_chars()
        for part in _PARA_SPLIT.split(text):
            start = text.find(part, pos)
            end = start + len(part)
            pos = end
            clean = " ".join(part.split())
            if not clean:
                continue
            rect = self._rect(textpage, start, min(end, n_chars), height)
            units.append(ParsedUnit(clean, {"kind": "page", "page": page_no, "rect": rect}))
        return units

    @staticmethod
    def _rect(textpage, start: int, end: int, height: float) -> list[float] | None:  # type: ignore[no-untyped-def]
        xs0, ys0, xs1, ys1 = [], [], [], []
        step = max(1, (end - start) // 400)  # sample long paragraphs
        for i in range(start, end, step):
            try:
                left, bottom, right, top = textpage.get_charbox(i)
            except Exception:
                continue
            if right - left <= 0:
                continue
            xs0.append(left)
            xs1.append(right)
            ys0.append(height - top)
            ys1.append(height - bottom)
        if not xs0:
            return None
        return [round(min(xs0), 1), round(min(ys0), 1), round(max(xs1), 1), round(max(ys1), 1)]

    def _ocr_units(self, page, page_no: int) -> list[ParsedUnit]:  # type: ignore[no-untyped-def]
        image = page.render(scale=OCR_SCALE).to_pil()
        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "page.png"
            image.save(img_path)
            lines = group_lines(ocr_lines(img_path))
        return [
            ParsedUnit(line.text, {"kind": "page", "page": page_no,
                                   "rect": [round(v / OCR_SCALE, 1) for v in line.box]})
            for line in lines if line.text.strip()
        ]
