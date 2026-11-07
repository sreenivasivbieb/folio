"""Sample files for tests, generated on the fly (no binary fixtures in the repo)."""

from __future__ import annotations

from pathlib import Path

MEETING_NOTES = """# Kickoff with Acme Corp

Priya Sharma <priya@example.com> leads the Atlas Project.

Priya Sharma owns the Acme Contract. The Acme Contract was signed on March 3, 2026.

Rahul Verma works at Acme Corp. Next review on April 14, 2026.
"""

CONTRACT_TEXT = [
    "MASTER SERVICES AGREEMENT",
    "This Acme Contract is between Acme Corp and Folio Labs.",
    "The Acme Contract was signed on March 3, 2026 by Priya Sharma.",
]

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.500
Welcome to the Atlas Project sync.

00:00:05.000 --> 00:00:09.000
Rahul Verma works at Acme Corp and joins us today.
"""

SRT = """1
00:00:01,000 --> 00:00:03,000
Budget review for the Atlas Project.

2
00:00:03,500 --> 00:00:06,000
Decision taken on May 2, 2026.
"""


def make_pdf(lines: list[str]) -> bytes:
    """A minimal valid one-page PDF with real text (Helvetica), built by hand."""
    content = "BT /F1 12 Tf 72 720 Td 16 TL\n" + "".join(
        "(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*\n"
        for ln in lines
    ) + "ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def write_samples(folder: Path) -> None:
    import docx

    (folder / "meeting-notes.md").write_text(MEETING_NOTES)
    (folder / "contract.pdf").write_bytes(make_pdf(CONTRACT_TEXT))
    (folder / "sync.vtt").write_text(VTT)
    (folder / "budget.srt").write_text(SRT)
    d = docx.Document()
    d.add_paragraph("Atlas Project status report")
    d.add_paragraph("Rahul Verma leads the Atlas Project from June 1, 2026.")
    d.save(str(folder / "status.docx"))
    (folder / "ignored.xyz").write_text("not a supported type")
