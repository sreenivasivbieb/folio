from __future__ import annotations

import mimetypes
import re

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from ...domain.errors import NotFound
from ...domain.models import Chunk, Root, Source
from ...ingestion.locations import DEFAULT_EXCLUSIONS, scan_locations
from ...store import repo
from ..deps import C
from ..dto import AddRoot, FileItem, Ok, ScanLocations, SourceDetail, SourcePage, TagRef

router = APIRouter(tags=["sources"])


@router.get("/roots", response_model=list[Root])
def list_roots(c: C) -> list[Root]:
    return c.ingestion.roots()


@router.post("/roots", response_model=Root)
def add_root(body: AddRoot, c: C) -> Root:
    """Select a file or folder. Nothing is copied or moved; indexing starts in the background."""
    root = c.ingestion.add_root(body.path, body.watch, body.include_hidden, body.exclude)
    c.watcher.sync()
    c.workers.notify()
    return root


@router.delete("/roots/{root_id}", response_model=Ok)
def remove_root(root_id: str, c: C) -> Ok:
    """Stop tracking a folder: its files leave the list and the index; knowledge is kept."""
    n = c.ingestion.remove_root(root_id)
    c.watcher.sync()
    return Ok(detail=f"{n} file(s) no longer tracked")


@router.post("/rescan", response_model=Ok)
def rescan(c: C) -> Ok:
    n = c.ingestion.rescan_all()
    c.workers.notify()
    return Ok(detail=f"{n} file(s) queued")


@router.get("/sources", response_model=list[Source])
def list_sources(c: C, root_id: str | None = None, limit: int = Query(1000, ge=1, le=5000)) -> list[Source]:
    query = {"status": {"$nin": repo.HIDDEN_SOURCE_STATUSES}, "kind": {"$ne": "other"}}
    if root_id:
        query["root_id"] = root_id
    return [repo.source_from_doc(d) for d in c.kdb["sources"].find(query).sort("path", 1).limit(limit)]


@router.get("/scan/locations", response_model=ScanLocations)
def locations(c: C) -> ScanLocations:
    return ScanLocations(locations=scan_locations(), default_exclusions=DEFAULT_EXCLUSIONS,
                         supported_extensions=c.ingestion.registry.extensions)


@router.get("/files", response_model=SourcePage)
def file_page(c: C, q: str = "", tag: str | None = None, offset: int = Query(0, ge=0),
              limit: int = Query(100, ge=1, le=500)) -> SourcePage:
    """The Library list, newest first, with each file's tags and description. ``tag`` narrows it
    to files organized under that topic/person/project."""
    query: dict = {"status": {"$nin": repo.HIDDEN_SOURCE_STATUSES}}
    if q:
        query["path"] = {"$regex": re.escape(q), "$options": "i"}
    if tag:
        query["_id"] = {"$in": repo.files_tagged(c.kdb, tag)}
    docs = list(c.kdb["sources"].find(query).sort([("updated_at", -1), ("_id", 1)]).skip(offset).limit(limit))
    org = repo.file_organization(c.kdb, [d["_id"] for d in docs])
    items = [FileItem(**repo.source_from_doc(d).model_dump(), **org.get(d["_id"], {})) for d in docs]
    return SourcePage(sources=items, total=c.kdb["sources"].count_documents(query), offset=offset, limit=limit)


@router.get("/files/tags", response_model=list[TagRef])
def file_tags(c: C) -> list[TagRef]:
    """Topics, projects, people... that files are organized under, most used first."""
    return [TagRef(**t) for t in repo.top_tags(c.kdb)]


@router.get("/sources/{source_id}", response_model=SourceDetail)
def get_source(source_id: str, c: C) -> SourceDetail:
    src = repo.get_source(c.kdb, source_id)
    if src is None:
        raise NotFound(f"source {source_id} not found")
    n = c.index.reader().execute("SELECT COUNT(*) FROM chunks WHERE source_id = ?", (source_id,)).fetchone()[0]
    org = repo.file_organization(c.kdb, [source_id]).get(source_id, {})
    return SourceDetail(source=src, chunks=n, **org)


@router.get("/sources/{source_id}/chunks", response_model=list[Chunk])
def source_chunks(source_id: str, c: C) -> list[Chunk]:
    return repo.chunks_for_source(c.index.reader(), source_id)


@router.post("/sources/{source_id}/reindex", response_model=Ok)
def reindex(source_id: str, c: C) -> Ok:
    c.kdb["sources"].update_one({"_id": source_id}, {"$set": {"indexed_hash": None, "status": "pending", "error": None}})
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
    """Empty index.db and re-index everything. Local knowledge is untouched."""
    c.index.reset()
    c.vectors.ensure()
    c.kdb["sources"].update_many({"status": {"$nin": repo.HIDDEN_SOURCE_STATUSES}},
                                 {"$set": {"indexed_hash": None, "status": "pending"}})
    n = c.ingestion.rescan_all()
    c.workers.notify()
    return Ok(detail=f"{n} file(s) queued")
