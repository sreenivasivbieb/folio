"""Drop -> label -> AI organize: the label-first intake flow."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import C

router = APIRouter(tags=["drops"])


class DropBody(BaseModel):
    paths: list[str] = Field(min_length=1)  # from the file/folder picker or a window drop
    mode: Literal["move", "copy"]


class LabelBody(BaseModel):
    label_text: str = Field(min_length=1)  # typed, or spoken and transcribed (English/Hindi/Hinglish)


class DropFile(BaseModel):
    source_id: str
    rel_path: str
    name: str
    kind: str
    status: str
    folder: str | None = None


class DropProject(BaseModel):
    id: str
    name: str


class Drop(BaseModel):
    id: str
    status: str  # importing | imported | organizing | organized | failed
    mode: str
    paths: list[str]
    file_count: int
    skipped: int
    label: str | None = None
    error: str | None = None
    engine: str | None = None  # the AI model, or "rules" offline
    created_at: str
    project: DropProject | None = None
    plan: dict[str, Any] | None = None
    files: list[DropFile] = Field(default_factory=list)
    disk: dict[str, Any] | None = None
    # imported / duplicates / failed / skipped counts once the import finished
    import_stats: dict[str, int] | None = None


class DiskMove(BaseModel):
    from_: str = Field(alias="from")
    to: str
    folder: str

    model_config = {"populate_by_name": True}


class DiskPreview(BaseModel):
    root: str
    moves: list[DiskMove]
    applied: bool


class DiskResult(BaseModel):
    root: str | None = None
    moved: int = 0
    restored: int = 0
    left: int = 0


class Transcript(BaseModel):
    transcript: str


@router.post("/drops", response_model=Drop)
def create_drop(body: DropBody, c: C) -> Drop:
    """Register dropped files/folders (junk skipped) and import them; then ask for a label."""
    drop = c.drops.create(body.paths, body.mode)
    c.workers.notify()
    return Drop(**drop)


@router.get("/drops", response_model=list[Drop])
def list_drops(c: C, limit: int = 50) -> list[Drop]:
    return [Drop(**d) for d in c.drops.list(limit)]


@router.get("/drops/{drop_id}", response_model=Drop)
def get_drop(drop_id: str, c: C) -> Drop:
    return Drop(**c.drops.get(drop_id))


@router.post("/drops/{drop_id}/label", response_model=Drop)
def label_drop(drop_id: str, body: LabelBody, c: C) -> Drop:
    """The user's words about the drop: the AI organizes the files from them."""
    drop = c.drops.set_label(drop_id, body.label_text)
    c.workers.notify()
    return Drop(**drop)


@router.post("/drops/{drop_id}/disk-organization/preview", response_model=DiskPreview)
def disk_preview(drop_id: str, c: C) -> DiskPreview:
    """Where each file would move inside the dropped folder. Nothing is moved."""
    return DiskPreview(**c.drops.disk_preview(drop_id))


@router.post("/drops/{drop_id}/apply-disk-organization", response_model=DiskResult)
def apply_disk(drop_id: str, c: C) -> DiskResult:
    """Move the files into the AI folders inside the dropped folder (only on explicit request)."""
    return DiskResult(**c.drops.disk_apply(drop_id))


@router.post("/drops/{drop_id}/disk-organization/undo", response_model=DiskResult)
def undo_disk(drop_id: str, c: C) -> DiskResult:
    return DiskResult(**c.drops.disk_undo(drop_id))


@router.post("/voice/transcribe", response_model=Transcript)
def transcribe(c: C) -> Transcript:
    """Stop push-to-talk and return the words only (for the drop label box)."""
    c.bus.publish({"type": "voice", "recording": False})
    return Transcript(transcript=c.labels.stop_text())
