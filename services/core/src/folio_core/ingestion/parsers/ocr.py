"""OCR via the Tesseract CLI (no Python binding needed). Optional: if ``tesseract`` is not on PATH,
scanned pages and images are indexed without text and the job message says so."""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OcrLine:
    text: str
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in image pixels (top-left origin)


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_lines(image_path: Path, lang: str = "eng") -> list[OcrLine]:
    out = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", lang, "tsv"],
        capture_output=True, text=True, timeout=300, check=True,
    ).stdout
    lines: dict[tuple[int, int, int], list[tuple[str, float, float, float, float]]] = {}
    for row in csv.DictReader(io.StringIO(out), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if not text or row.get("level") != "5":
            continue
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        x, y, w, h = (float(row[k]) for k in ("left", "top", "width", "height"))
        lines.setdefault(key, []).append((text, x, y, x + w, y + h))
    result = []
    for words in lines.values():
        result.append(OcrLine(
            " ".join(w[0] for w in words),
            (min(w[1] for w in words), min(w[2] for w in words),
             max(w[3] for w in words), max(w[4] for w in words)),
        ))
    return result


def group_lines(lines: list[OcrLine], gap_factor: float = 1.2) -> list[OcrLine]:
    """Merge OCR lines into paragraphs when the vertical gap is small."""
    paras: list[OcrLine] = []
    for line in lines:
        if paras:
            prev = paras[-1]
            height = prev.box[3] - prev.box[1]
            last_line_h = line.box[3] - line.box[1]
            if line.box[1] - prev.box[3] < gap_factor * max(last_line_h, 1) and height < 2000:
                paras[-1] = OcrLine(
                    f"{prev.text} {line.text}",
                    (min(prev.box[0], line.box[0]), prev.box[1],
                     max(prev.box[2], line.box[2]), line.box[3]),
                )
                continue
        paras.append(line)
    return paras
