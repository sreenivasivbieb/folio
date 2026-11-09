"""Request/response models. These define the OpenAPI spec from which the UI's TypeScript client is
generated (packages/api-client), so the UI and core cannot drift apart silently."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..domain.models import Claim, Entity, Label, Source

TargetKind = Literal["source", "chunk", "entity", "claim", "none"]


# --- requests -------------------------------------------------------------------------------


class AddRoot(BaseModel):
    path: str
    watch: bool = True
    include_hidden: bool = False
    exclude: list[str] | None = None


class ScanLocation(BaseModel):
    path: str
    label: str
    kind: str


class ScanLocations(BaseModel):
    locations: list[ScanLocation]
    default_exclusions: list[str]
    supported_extensions: list[str]


class TagRef(BaseModel):
    id: str
    name: str
    type: str
    count: int = 0  # files carrying this tag (in the tag list)


class FileItem(Source):
    """A file plus what labels said about it, so the Library shows how things are organized."""
    tags: list[TagRef] = Field(default_factory=list)
    description: str | None = None


class SourcePage(BaseModel):
    sources: list[FileItem]
    total: int
    offset: int
    limit: int


class CreateEntity(BaseModel):
    type: str
    name: str


class UpdateEntity(BaseModel):
    name: str | None = None
    type: str | None = None
    status: Literal["auto", "verified", "rejected"] | None = None


class AliasBody(BaseModel):
    alias: str


class MergeBody(BaseModel):
    keep_id: str
    merge_id: str


class SplitBody(BaseModel):
    name: str
    claim_ids: list[str]
    type: str | None = None


class CreateClaim(BaseModel):
    subject_id: str
    predicate: str
    value: Any = None
    object_id: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


class EditClaim(BaseModel):
    subject_id: str | None = None
    predicate: str | None = None
    value: Any = None
    object_id: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


class ClaimStatusBody(BaseModel):
    claim_ids: list[str]
    status: Literal["proposed", "verified", "rejected"]


class Target(BaseModel):
    target_kind: TargetKind = "none"
    target_ids: list[str] = Field(default_factory=list)


class TypedLabel(Target):
    transcript: str


class TranscriptBody(BaseModel):
    transcript: str


class AnswerBody(BaseModel):
    question_id: str
    value: str


class UndoBody(BaseModel):
    group_id: str | None = None


class SchemaBody(BaseModel):
    yaml: str


class CloudBody(BaseModel):
    enabled: bool


class DriveConnect(BaseModel):
    client_id: str
    client_secret: str | None = None


class DriveStatus(BaseModel):
    connected: bool
    client_id: str
    secret_configured: bool


class DriveAuthorization(BaseModel):
    authorization_url: str


class DriveBackup(BaseModel):
    id: str
    name: str
    size: str | None = None
    modifiedTime: str | None = None


class DriveBackups(BaseModel):
    files: list[DriveBackup]
    nextPageToken: str | None = None


class DriveRestore(BaseModel):
    file_id: str


# --- responses ------------------------------------------------------------------------------


class Ok(BaseModel):
    ok: bool = True
    detail: str | None = None


class GroupRef(BaseModel):
    group_id: str


class ClaimRef(BaseModel):
    claim_id: str | None


class EntityNode(BaseModel):
    id: str
    name: str
    type: str
    status: str
    degree: int = 0


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    predicate: str
    status: str
    confidence: float


class GraphView(BaseModel):
    nodes: list[EntityNode]
    edges: list[GraphEdge]


class TimelineView(BaseModel):
    entity: Entity | None
    items: list[Claim]
    entities: dict[str, EntityNode]


class Lane(BaseModel):
    id: str
    title: str
    type: str
    items: list[Claim]


class SwimlaneView(BaseModel):
    group_by: str
    lanes: list[Lane]
    entities: dict[str, EntityNode]


class TableView(BaseModel):
    claims: list[Claim]
    entities: dict[str, EntityNode]
    offset: int = 0
    limit: int = 100
    has_more: bool = False


class ClaimInCard(Claim):
    direction: Literal["in", "out"]


class FileRef(BaseModel):
    id: str
    path: str
    kind: str


class Passage(BaseModel):
    chunk_id: str
    source_id: str
    path: str
    kind: str
    text: str
    locator: dict[str, Any]
    score: float


class EntityCard(BaseModel):
    entity: Entity
    groups: dict[str, list[ClaimInCard]]
    related: dict[str, EntityNode]
    files: list[FileRef]
    passages: list[Passage]
    counts: dict[str, int]


class FileHit(BaseModel):
    source_id: str
    path: str
    kind: str
    status: str
    via: str  # why it matched: the topic/entity name, a label, or "file name"


class SearchResult(BaseModel):
    entities: list[Entity]
    passages: list[Passage]
    files: list[FileHit] = []


class Conflict(BaseModel):
    subject_id: str
    predicate: str
    claims: list[Claim]


class MergeSuggestion(BaseModel):
    id: str
    entity_a: str
    entity_b: str
    score: float
    reason: str
    status: str
    created_at: str


class ExtractionIssue(BaseModel):
    id: str
    source_id: str
    chunk_id: str | None
    reason: str
    path: str | None
    created_at: str


class ReviewView(BaseModel):
    conflicts: list[Conflict]
    flagged: list[Claim]
    proposed: list[Claim]
    merge_suggestions: list[MergeSuggestion]
    extraction_issues: list[ExtractionIssue]
    entities: dict[str, Entity]
    total_proposed: int


class ProviderInfo(BaseModel):
    kind: str
    model: str
    local: bool


class VoiceStatus(BaseModel):
    recording: bool
    microphone: bool
    microphone_detail: str
    speech_model: str
    speech_available: bool
    speech_downloadable: bool
    speech_size_mb: int
    speech_engine: str = "none"  # local | cloud | none


class LLMStatus(BaseModel):
    configured: bool
    provider: str | None = None
    label: str | None = None
    base_url: str | None = None
    model: str | None = None
    local: bool = True
    key_hint: str | None = None  # "…a1b2" — the key itself is never returned


class Status(BaseModel):
    version: str
    data_dir: str
    cloud_enabled: bool
    network_mode: Literal["local", "cloud"]
    extractor: str
    llm: LLMStatus
    providers: list[ProviderInfo]
    voice: VoiceStatus
    jobs: dict[str, int]
    counts: dict[str, int]
    types: list[str]
    vector_backend: str
    supported_extensions: list[str]


class PresetView(BaseModel):
    id: str
    label: str
    base_url: str
    needs_key: bool
    key_url: str | None = None
    suggested_models: list[str] = []


class LLMSettingsView(BaseModel):
    status: LLMStatus
    presets: list[PresetView]


class LLMSettingsBody(BaseModel):
    provider: str
    base_url: str
    model: str
    api_key: str | None = None  # None = keep the stored key; "" = remove it


class ModelsBody(BaseModel):
    provider: str
    base_url: str
    api_key: str | None = None  # optional: use before saving; else the stored key


class SchemaView(BaseModel):
    version: int
    schema_: dict[str, Any] = Field(alias="schema")
    yaml: str

    model_config = {"populate_by_name": True}


class HistoryEntry(BaseModel):
    seq: int
    ts: str
    op: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    group_id: str
    actor: str
    action: str
    summary: str


class GroupEntry(BaseModel):
    seq: int
    id: str
    ts: str
    actor: str
    action: str
    summary: str
    undoes: str | None
    n_events: int
    undone: bool


class SourceDetail(BaseModel):
    source: Source
    chunks: int


class VoiceToggle(BaseModel):
    state: Literal["recording", "stopped"]
    label: Label | None = None


class Acceptance(BaseModel):
    type: str
    week: str
    verified: int
    rejected: int
    proposed: int
    rate: float | None

