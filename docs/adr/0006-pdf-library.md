# 0006 — pypdfium2 instead of PyMuPDF

**Context.** The proposal listed PyMuPDF as a *candidate*. PyMuPDF is AGPL-3.0; shipping it in a
distributed desktop app forces AGPL on the whole app or a commercial licence.

**Decision.** Use `pypdfium2` (Apache-2.0/BSD; PDFium) for text + character boxes, rendering scans
to images for Tesseract OCR (called as a CLI, so no Python binding is bundled).

**Consequences.** Licence-safe. Region locators are computed from PDFium char boxes. Layout-aware
conversion (tables, reading order) can be added later as another parser plugin.
