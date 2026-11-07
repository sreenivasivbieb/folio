"""Ingestion: parsers + locators (FR-2), hashing (FR-1), sandboxing, forgetting."""

from pathlib import Path

from folio_core.domain.models import ClaimStatus, SourceStatus
from folio_core.ingestion.base import ParsedUnit
from folio_core.ingestion.chunker import chunk_units
from folio_core.ingestion.parsers.subtitles import parse_timestamp
from folio_core.ingestion.registry import ParserRegistry
from folio_core.ingestion.sandbox import run_sandboxed
from folio_core.store import repo

from .conftest import drain


def test_every_chunk_has_a_locator(container, files):
    container.ingestion.add_root(str(files))
    drain(container)
    conn = container.db.reader()
    by_kind = {}
    for src in repo.list_sources(conn):
        assert src.status == SourceStatus.INDEXED, (src.path, src.error)
        for ch in repo.chunks_for_source(conn, src.id):
            by_kind.setdefault(src.kind.value, []).append(ch.locator)
    assert {"pdf", "markdown", "subtitle", "docx"} <= set(by_kind)
    pdf = by_kind["pdf"][0]
    assert pdf.kind == "page" and pdf.page == 1 and pdf.rect and pdf.rect[2] > pdf.rect[0]
    assert all(loc.kind == "time" and loc.end >= loc.start for loc in by_kind["subtitle"])
    assert all(loc.kind == "text" and loc.line_start >= 1 for loc in by_kind["markdown"])
    # unsupported files are ignored, originals untouched
    assert not any(s.path.endswith(".xyz") for s in repo.list_sources(conn))


def test_unchanged_file_costs_nothing_changed_file_reindexes(container, files):
    container.ingestion.add_root(str(files))
    drain(container)
    src = next(s for s in repo.list_sources(container.db.reader()) if s.path.endswith(".md"))

    # Force a re-check of an unchanged file: content hash matches -> no parse, no extraction.
    extracts = lambda: sum(j.kind == "extract_source" for j in container.queue.list(limit=1000))  # noqa: E731
    before = extracts()
    job_id = container.queue.enqueue("index_source", {"source_id": src.id})
    drain(container)
    assert "unchanged" in container.queue.get(job_id).message
    assert extracts() == before  # no extraction (and so no model call) was queued

    path = Path(src.path)
    path.write_text(path.read_text() + "\nBob Stone works at Initech.\n")
    container.ingestion.scan_path(path)
    drain(container)
    texts = " ".join(c.text for c in repo.chunks_for_source(container.db.reader(), src.id))
    assert "Initech" in texts


def test_parser_crash_is_contained_and_reported(container, tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    container.ingestion.add_root(str(bad))
    drain(container)
    src = repo.list_sources(container.db.reader())[0]
    assert src.status == SourceStatus.FAILED
    job = container.queue.list("failed")[0]
    assert "parser exited" in job.error


def test_sandbox_round_trip(files):
    units = run_sandboxed("text", files / "meeting-notes.md", timeout_s=60, memory_mb=1024)
    assert units and units[0].locator["kind"] == "text"


def test_subtitles_and_chunker():
    assert parse_timestamp("01:02:03.500") == 3723.5
    assert parse_timestamp("02:03,250") == 123.25
    reg = ParserRegistry(load_plugins=False)
    _parser, kind = reg.for_path(Path("x.vtt"))
    assert kind.value == "subtitle"
    units = [ParsedUnit("a" * 50, {"kind": "time", "start": i * 5.0, "end": i * 5.0 + 4}) for i in range(30)]
    chunks = chunk_units(units)
    assert all(c.locator["end"] - c.locator["start"] <= 60 for c in chunks)
    assert chunks[0].locator["start"] == 0.0


def test_forget_file_removes_unverified_and_flags_verified(container, files):
    container.ingestion.add_root(str(files))
    drain(container)
    conn = container.db.reader()
    src = next(s for s in repo.list_sources(conn) if s.path.endswith(".md"))
    claims = repo.query_claims(conn, source_id=src.id)
    only_here = [c for c in claims if {e.source_id for e in c.evidence} == {src.id}]
    keep = only_here[0]
    container.knowledge.set_claim_status([keep.id], ClaimStatus.VERIFIED)

    stats = container.ingestion.forget_source(src.id)
    assert stats["claims_flagged"] == 1 and stats["claims_removed"] >= 1
    assert repo.chunks_for_source(conn, src.id) == []
    flagged = repo.get_claim(conn, keep.id)
    assert flagged.needs_review and flagged.status.value == "verified"
    # a forgotten file is never re-indexed by later scans
    container.ingestion.rescan_all()
    assert repo.get_source(conn, src.id).status == SourceStatus.FORGOTTEN
