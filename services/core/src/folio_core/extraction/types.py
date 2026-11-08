"""What an extractor returns: *candidates* by name, before entity resolution.

The same Pydantic models produce the JSON schema handed to an LLM for constrained output, and
validate whatever comes back (FR-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..domain.schema import SchemaDef
from ..learning import GazetteerEntry


class CandidateEntity(BaseModel):
    name: str
    type: str


class CandidateClaim(BaseModel):
    subject: str = Field(description="Name of the entity the claim is about")
    subject_type: str = Field(description="Short type name, e.g. Person, Topic, Course, Organization")
    predicate: str = Field(description="snake_case attribute or relation name, e.g. teaches, part_of, email")
    value: str | float | int | bool | None = Field(default=None, description="Literal value for attributes")
    object: str | None = Field(default=None, description="Object entity name for relations")
    object_type: str | None = None
    valid_from: str | None = Field(default=None, description="ISO date the fact applies from")
    confidence: float = Field(ge=0, le=1)
    quote: str = Field(description="Exact span from the text that states this fact")


class ExtractionOutput(BaseModel):
    entities: list[CandidateEntity] = Field(default_factory=list)
    claims: list[CandidateClaim] = Field(default_factory=list)


@dataclass
class ExtractionContext:
    schema: SchemaDef
    gazetteer: list[GazetteerEntry]
    document_name: str
    few_shot: list[dict[str, Any]] = field(default_factory=list)
    negatives: list[dict[str, Any]] = field(default_factory=list)


class Extractor(Protocol):
    model_id: str
    prompt_version: str
    uses_llm: bool

    def extract(self, text: str, ctx: ExtractionContext) -> ExtractionOutput: ...


class ExtractionFailed(Exception):
    """Output failed validation twice; the chunk goes to the review queue."""

    def __init__(self, reason: str, raw: str | None = None) -> None:
        super().__init__(reason)
        self.raw = raw
