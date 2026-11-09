from __future__ import annotations

import contextlib
from pathlib import Path

from ...domain.models import SourceKind
from ..base import ParseContext, ParsedUnit
from .ocr import group_lines, ocr_lines, tesseract_available


class ImageParser:
    """Images: OCR text with pixel regions. Captions/CLIP embeddings plug in here later (the
    provider interface exists; v1 ships OCR so it stays small and fully offline)."""

    name = "image"
    extensions = {ext: SourceKind.IMAGE for ext in
                  (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif")}
    sandboxed = True

    def parse(self, path: Path, ctx: ParseContext) -> list[ParsedUnit]:
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(path) as img:
                width, height = img.size
                exif_date = None
                with contextlib.suppress(Exception):
                    exif_date = img.getexif().get(306)  # DateTime
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            # Scientific/GeoTIFF rasters, truncated or exotic files: index the name, don't fail.
            return [ParsedUnit(f"Image {path.name} (format not readable for preview or OCR)",
                               {"kind": "region", "rect": [0, 0, 0, 0]})]
        units: list[ParsedUnit] = []
        if tesseract_available():
            for line in group_lines(ocr_lines(path)):
                units.append(ParsedUnit(line.text, {"kind": "region", "rect": list(line.box)}))
        if not units:
            desc = f"Image {path.name} ({width}x{height})"
            if exif_date:
                desc += f", taken {exif_date}"
            units.append(ParsedUnit(desc, {"kind": "region", "rect": [0, 0, width, height]}))
        return units
