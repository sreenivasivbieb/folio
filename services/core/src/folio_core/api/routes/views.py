"""Read models for the UI: the four views, search and the review queue."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ...store import repo
from ..deps import C
from ..dto import GraphView, Ok, ReviewView, SearchResult, SwimlaneView, TableView, TimelineView

router = APIRouter(tags=["views"])


@router.get("/views/graph", response_model=GraphView)
def graph(c: C, entity_id: str | None = None, depth: int = 2, limit: int = 2000,
          include_rejected: bool = False, include_mentions: bool = False,
          type: list[str] | None = Query(default=None)) -> GraphView:
    return GraphView.model_validate(c.views.graph(entity_id, depth, limit, include_rejected,
                                                  include_mentions, type))


@router.get("/views/timeline/{entity_id}", response_model=TimelineView)
def timeline(entity_id: str, c: C, include_rejected: bool = False) -> TimelineView:
    return TimelineView.model_validate(c.views.timeline(entity_id, include_rejected))


@router.get("/views/swimlane", response_model=SwimlaneView)
def swimlane(c: C, group_by: str = "entity", entity_id: list[str] | None = Query(default=None),
             type: list[str] | None = Query(default=None),
             include_rejected: bool = False) -> SwimlaneView:
    return SwimlaneView.model_validate(c.views.swimlane(group_by, entity_id, type, include_rejected))


@router.get("/views/table", response_model=TableView)
def table(c: C, entity_id: str | None = None, status: list[str] | None = Query(default=None),
          predicate: str | None = None, entity_type: str | None = None,
          min_confidence: float | None = None, include_mentions: bool = False,
          order: str = "recent", limit: int = Query(100, ge=1, le=1000),
          offset: int = Query(0, ge=0)) -> TableView:
    """Table view: claims for an entity or a filter, sortable, with bulk verify/reject."""
    data = c.views.table(entity_id=entity_id, status=status, predicate=predicate,
                         exclude_predicates=None if include_mentions else ["mentions"],
                         entity_type=entity_type, min_confidence=min_confidence, order=order,
                         limit=limit + 1, offset=offset)
    data["has_more"] = len(data["claims"]) > limit
    data["claims"] = data["claims"][:limit]
    data.update(offset=offset, limit=limit)
    return TableView.model_validate(data)


@router.get("/search", response_model=SearchResult)
def search(q: str, c: C, k: int = 20) -> SearchResult:
    """Entity query by text (voice queries use the same endpoint with the transcript)."""
    if len(q.strip()) < 2:  # before typing: recent files and the most connected entities
        return SearchResult(entities=repo.search_entities(c.kdb, "", limit=8), passages=[],
                            files=c.search.recent_files(8))  # type: ignore[arg-type]
    entities = repo.search_entities(c.kdb, q, limit=10)
    return SearchResult(entities=entities, passages=c.search.search(q, k),  # type: ignore[arg-type]
                        files=c.search.files(q, entities))  # type: ignore[arg-type]


@router.get("/review", response_model=ReviewView)
def review(c: C, limit: int = 100, max_confidence: float = 0.75) -> ReviewView:
    return ReviewView.model_validate(c.review.queue(limit, max_confidence))


@router.post("/review/suggestions/{suggestion_id}/dismiss", response_model=Ok)
def dismiss_suggestion(suggestion_id: str, c: C) -> Ok:
    c.review.dismiss_suggestion(suggestion_id)
    c.bus.publish({"type": "review"})
    return Ok()


@router.post("/review/issues/{issue_id}/dismiss", response_model=Ok)
def dismiss_issue(issue_id: str, c: C) -> Ok:
    c.review.dismiss_issue(issue_id)
    c.bus.publish({"type": "review"})
    return Ok()
