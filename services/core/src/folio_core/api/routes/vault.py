"""Dump files into Folio (moved or copied into its own storage), trash, restore and export."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import C
from ..dto import Ok

router = APIRouter(tags=["vault"])


class ImportBody(BaseModel):
    paths: list[str] = Field(min_length=1)
    mode: Literal["move", "copy"]  # chosen by the user every time


class ExportBody(BaseModel):
    mode: Literal["move", "copy"]
    dest_dir: str | None = None  # None: back to where the file originally came from


class TrashItem(BaseModel):
    id: str
    name: str
    kind: str | None = None
    size: int = 0
    trashed_at: str | None = None
    origin_path: str | None = None


class VaultInfo(BaseModel):
    path: str
    files: int
    bytes: int
    trashed: int


@router.get("/vault", response_model=VaultInfo)
def info(c: C) -> VaultInfo:
    root = c.vault.root()
    live = list(c.kdb["sources"].find({"root_id": root.id, "status": {"$nin": ["trashed", "forgotten", "removed"]}},
                                      {"size": 1}))
    return VaultInfo(path=str(c.vault.dir), files=len(live), bytes=sum(d.get("size") or 0 for d in live),
                     trashed=c.kdb["sources"].count_documents({"status": "trashed"}))


@router.post("/vault/import", response_model=Ok)
def import_files(body: ImportBody, c: C) -> Ok:
    """Queue the import; progress shows in Activity. The list of paths comes from the file picker
    or from files dropped onto the window."""
    c.vault._expand(body.paths)  # validate now, so a bad path is reported immediately
    c.queue.enqueue("vault_import", {"paths": body.paths, "mode": body.mode}, priority=30)
    c.workers.notify()
    return Ok(detail="Adding to Folio…")


@router.post("/vault/{source_id}/trash", response_model=Ok)
def trash(source_id: str, c: C) -> Ok:
    c.vault.trash(source_id)
    return Ok(detail="Moved to Folio's trash")


@router.post("/vault/{source_id}/restore", response_model=Ok)
def restore(source_id: str, c: C) -> Ok:
    c.vault.restore(source_id)
    c.workers.notify()
    return Ok(detail="Restored")


@router.delete("/vault/{source_id}", response_model=Ok)
def delete_forever(source_id: str, c: C) -> Ok:
    c.vault.delete_forever(source_id)
    return Ok(detail="Deleted permanently")


@router.get("/vault/trash", response_model=list[TrashItem])
def trash_list(c: C) -> list[TrashItem]:
    return [TrashItem(**t) for t in c.vault.trash_list()]


@router.post("/vault/trash/empty", response_model=Ok)
def empty_trash(c: C) -> Ok:
    return Ok(detail=f"{c.vault.empty_trash()} file(s) deleted permanently")


@router.post("/vault/{source_id}/export", response_model=Ok)
def export(source_id: str, body: ExportBody, c: C) -> Ok:
    return Ok(detail=c.vault.export(source_id, body.dest_dir, body.mode))
