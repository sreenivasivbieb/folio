from __future__ import annotations

import mimetypes

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ...domain.models import Chunk, Root, Source
from ...store import repo
from ..deps import C
from ..dto import AddRoot, Ok, SourceDetail

router = APIRouter(tags=["sources"])


@router.get("/roots", response_model=list[Root])
def list_roots(c: C) -> list[Root]:
    return c.ingestion.roots()


@router.post("/roots", response_model=Root)
def add_root(body: AddRoot, c: C) -> Root:
    """Select a file or folder. Nothing is copied or moved; indexing starts in the background."""
    root = c.ingestion.add_root(body.path, body.watch)
    c.watcher.sync()
    c.workers.notify()
    return root


@router.delete("/roots/{root_id}", response_model=Ok)
def remove_root(root_id: str, c: C) -> Ok:
    c.ingestion.remove_root(root_id)
    return Ok()


@router.post("/rescan", response_model=Ok)
def rescan(c: C) -> Ok:
    n = c.ingestion.rescan_all()
    c.workers.notify()
    return Ok(detail=f"{n} file(s) queued")


@router.get("/sources", response_model=list[Source])
def list_sources(c: C, root_id: str | None = None) -> list[Source]:
    return repo.list_sources(c.db.reader(), root_id)


@router.get("/sources/{source_id}", response_model=SourceDetail)
def get_source(source_id: str, c: C) -> SourceDetail:
    conn = c.db.reader()
    src = repo.get_source(conn, source_id)
    if src is None:
        from ...domain.errors import NotFound

        raise NotFound(f"source {source_id} not found")
    n = conn.execute("SELECT COUNT(*) FROM ix.chunks WHERE source_id = ?", (source_id,)).fetchone()[0]
    return SourceDetail(source=src, chunks=n)


@router.get("/sources/{source_id}/chunks", response_model=list[Chunk])
def source_chunks(source_id: str, c: C) -> list[Chunk]:
    return repo.chunks_for_source(c.db.reader(), source_id)


@router.post("/sources/{source_id}/reindex", response_model=Ok)
def reindex(source_id: str, c: C) -> Ok:
    with c.db.write() as conn:
        conn.execute("UPDATE sources SET indexed_hash = NULL, status = 'pending' WHERE id = ?", (source_id,))
    c.queue.enqueue("index_source", {"source_id": source_id}, dedupe_key=f"index:{source_id}", priority=10)
    c.workers.notify()
    return Ok()


@router.post("/sources/{source_id}/forget", response_model=dict[str, int])
def forget(source_id: str, c: C) -> dict[str, int]:
    """Right to forget: drop chunks, embeddings and unverified claims of this file."""
    return c.ingestion.forget_source(source_id)


@router.get("/sources/{source_id}/file", response_class=FileResponse)
def source_file(source_id: str, c: C) -> FileResponse:
    """Stream the original (read-only) so the UI can show evidence at the page/second."""
    path = c.ingestion.source_path(source_id)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, content_disposition_type="inline")


@router.post("/index/rebuild", response_model=Ok)
def rebuild_index(c: C) -> Ok:
    """Delete index.db and re-index everything. User knowledge (knowledge.db) is untouched."""
    c.db.reset_index()
    with c.db.write() as conn:
        conn.execute("UPDATE sources SET indexed_hash = NULL, status = 'pending' WHERE status != 'forgotten'")
    from ...store.vectors import VectorIndex

    vectors = VectorIndex(c.db, c.providers.embedder.dim, c.providers.embedder.model_id)
    c.ingestion.vectors = vectors
    c.search.vectors = vectors
    n = c.ingestion.rescan_all()
    c.workers.notify()
    return Ok(detail=f"{n} file(s) queued")
