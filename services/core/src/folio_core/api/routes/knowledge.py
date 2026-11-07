"""Entities and claims: read, inline edit, merge, split, verify, reject (FR-5, FR-7)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...domain.errors import NotFound
from ...domain.models import Claim, ClaimStatus, Entity, EntityStatus, Extractor
from ...store import repo
from ..deps import C
from ..dto import (
    AliasBody,
    ClaimRef,
    ClaimStatusBody,
    CreateClaim,
    CreateEntity,
    EditClaim,
    EntityCard,
    HistoryEntry,
    MergeBody,
    Ok,
    SplitBody,
    UpdateEntity,
)

router = APIRouter(tags=["knowledge"])


# --- entities -------------------------------------------------------------------------------


@router.get("/entities", response_model=list[Entity])
def list_entities(c: C, q: str = "", type: list[str] | None = Query(default=None),
                  include_rejected: bool = False, limit: int = 100) -> list[Entity]:
    return repo.search_entities(c.db.reader(), q, type, include_rejected, limit)


@router.post("/entities", response_model=Entity)
def create_entity(body: CreateEntity, c: C) -> Entity:
    return c.knowledge.create_entity(body.type, body.name)


@router.get("/entities/{entity_id}", response_model=EntityCard)
def entity_card(entity_id: str, c: C) -> EntityCard:
    return EntityCard.model_validate(c.cards.card(entity_id))


@router.patch("/entities/{entity_id}", response_model=Entity)
def update_entity(entity_id: str, body: UpdateEntity, c: C) -> Entity:
    status = EntityStatus(body.status) if body.status else None
    return c.knowledge.update_entity(entity_id, name=body.name, type=body.type, status=status)


@router.post("/entities/{entity_id}/aliases", response_model=Entity)
def add_alias(entity_id: str, body: AliasBody, c: C) -> Entity:
    return c.knowledge.add_alias(entity_id, body.alias)


@router.delete("/entities/{entity_id}/aliases", response_model=Entity)
def remove_alias(entity_id: str, alias: str, c: C) -> Entity:
    return c.knowledge.remove_alias(entity_id, alias)


@router.post("/entities/merge", response_model=Entity)
def merge(body: MergeBody, c: C) -> Entity:
    return c.knowledge.merge_entities(body.keep_id, body.merge_id)


@router.post("/entities/{entity_id}/split", response_model=Entity)
def split(entity_id: str, body: SplitBody, c: C) -> Entity:
    return c.knowledge.split_entity(entity_id, body.name, body.claim_ids, body.type)


@router.get("/entities/{entity_id}/history", response_model=list[HistoryEntry])
def entity_history(entity_id: str, c: C) -> list[HistoryEntry]:
    return [HistoryEntry(**h) for h in c.ledger.history("entities", entity_id)]


# --- claims ---------------------------------------------------------------------------------


@router.get("/claims", response_model=list[Claim])
def list_claims(
    c: C, entity_id: str | None = None, status: list[str] | None = Query(default=None),
    predicate: str | None = None, entity_type: str | None = None, kind: str | None = None,
    min_confidence: float | None = None, max_confidence: float | None = None,
    source_id: str | None = None, dated_only: bool = False, needs_review: bool | None = None,
    order: str = "recent", limit: int = 500, offset: int = 0,
) -> list[Claim]:
    """The table view: every claim for an entity or a filter."""
    return repo.query_claims(
        c.db.reader(), entity_id=entity_id, status=status, predicate=predicate,
        entity_type=entity_type, kind=kind, min_confidence=min_confidence,
        max_confidence=max_confidence, source_id=source_id, dated_only=dated_only,
        needs_review=needs_review, order=order, limit=limit, offset=offset,
    )


@router.post("/claims", response_model=ClaimRef)
def create_claim(body: CreateClaim, c: C) -> ClaimRef:
    claim_id = c.knowledge.add_claim(
        subject_id=body.subject_id, predicate=body.predicate, value=body.value,
        object_id=body.object_id, valid_from=body.valid_from, valid_to=body.valid_to,
        status=ClaimStatus.VERIFIED, extractor=Extractor(kind="user"),
    )
    return ClaimRef(claim_id=claim_id)


@router.get("/claims/{claim_id}", response_model=Claim)
def get_claim(claim_id: str, c: C) -> Claim:
    claim = repo.get_claim(c.db.reader(), claim_id)
    if claim is None:
        raise NotFound(f"claim {claim_id} not found")
    return claim


@router.patch("/claims/{claim_id}", response_model=ClaimRef)
def edit_claim(claim_id: str, body: EditClaim, c: C) -> ClaimRef:
    return ClaimRef(claim_id=c.knowledge.edit_claim(claim_id, body.model_dump(exclude_unset=True)))


@router.post("/claims/status", response_model=Ok)
def claim_status(body: ClaimStatusBody, c: C) -> Ok:
    n = c.knowledge.set_claim_status(body.claim_ids, ClaimStatus(body.status))
    return Ok(detail=f"{n} claim(s) {body.status}")


@router.get("/claims/{claim_id}/history", response_model=list[HistoryEntry])
def claim_history(claim_id: str, c: C) -> list[HistoryEntry]:
    """FR-10: who or what made the claim, with which model/prompt, and every later change."""
    return [HistoryEntry(**h) for h in c.ledger.history("claims", claim_id)]
