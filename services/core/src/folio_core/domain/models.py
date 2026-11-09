"""Core domain objects (see the "Data model" section of the architecture proposal).

The unit of knowledge is the **claim**: one statement about an entity, with evidence, time and
status. Relations are claims whose object is another entity, so the graph, timeline and swimlane
views are projections of the same documents.

Open schema: ``Entity.type`` and ``Claim.predicate`` are free strings and ``Claim.value`` is any
JSON value. Only the trust envelope (status, provenance, evidence) has a fixed shape.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceKind(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    MARKDOWN = "markdown"
    TEXT = "text"
    SUBTITLE = "subtitle"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER = "other"


class SourceStatus(StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    MISSING = "missing"
    FORGOTTEN = "forgotten"  # the user asked to forget it: never re-indexed
    REMOVED = "removed"  # its folder was removed from Folio: knowledge kept, index dropped
    METADATA = "metadata"  # searchable file information; no parser for its contents


class EntityStatus(StrEnum):
    AUTO = "auto"  # created by a model, not yet confirmed
    VERIFIED = "verified"  # confirmed or created by the user
    REJECTED = "rejected"
    MERGED = "merged"  # folded into another entity (see merged_into)


class ClaimStatus(StrEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ClaimKind(StrEnum):
    ATTRIBUTE = "attribute"  # value is a literal
    RELATION = "relation"  # object_id points to another entity


class Locator(BaseModel):
    """Where inside a source a piece of evidence lives.

    kind="page": PDF page (1-based) and optional rect [x0, y0, x1, y1] in PDF points.
    kind="region": image region in pixels.
    kind="time": media start/end in seconds.
    kind="text": line range in a text-like file (1-based, inclusive).
    kind="label": the evidence is a voice/typed label.
    """

    kind: Literal["page", "region", "time", "text", "label"]
    page: int | None = None
    rect: list[float] | None = None
    start: float | None = None
    end: float | None = None
    line_start: int | None = None
    line_end: int | None = None
    label_id: str | None = None


class Extractor(BaseModel):
    """Who or what made a claim (FR-10 provenance)."""

    kind: Literal["model", "user", "voice", "import", "system"]
    model: str | None = None
    prompt_version: str | None = None


class Root(BaseModel):
    id: str
    path: str
    kind: Literal["file", "folder"]
    watch: bool
    created_at: str
    include_hidden: bool = False
    exclude: list[str] = Field(default_factory=list)


class Source(BaseModel):
    id: str
    root_id: str | None
    path: str
    kind: SourceKind
    size: int
    mtime: float
    content_hash: str | None
    indexed_hash: str | None
    status: SourceStatus
    error: str | None = None
    updated_at: str


class Chunk(BaseModel):
    id: str
    source_id: str
    ord: int
    text: str
    locator: Locator
    content_hash: str


class Entity(BaseModel):
    id: str
    type: str
    name: str
    status: EntityStatus
    created_by: str
    merged_into: str | None = None
    created_at: str
    updated_at: str
    aliases: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    id: str
    claim_id: str
    source_id: str | None
    chunk_id: str | None = None
    locator: Locator
    quote: str
    label_id: str | None = None


class Claim(BaseModel):
    id: str
    subject_id: str
    predicate: str
    kind: ClaimKind
    value: Any = None
    object_id: str | None = None
    valid_from: str | None = None  # ISO date
    valid_to: str | None = None
    confidence: float
    status: ClaimStatus
    extractor: Extractor
    fingerprint: str
    label_id: str | None = None
    needs_review: bool = False
    created_at: str
    updated_at: str
    evidence: list[Evidence] = Field(default_factory=list)


class Label(BaseModel):
    id: str
    transcript: str
    audio_path: str | None
    target_kind: Literal["source", "chunk", "entity", "claim", "none"]
    target_ids: list[str]
    parsed: dict[str, Any]
    status: Literal["preview", "committed", "cancelled"]
    created_at: str
