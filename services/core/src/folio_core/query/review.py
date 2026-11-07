"""Review queue: the riskiest facts first, so a few minutes of review covers what matters.

Order: conflicts (same subject + single-valued attribute, different values) -> claims flagged for
review (e.g. their only source was forgotten) -> proposed claims by ascending confidence.
Merge suggestions and failed extractions are listed alongside.
"""

from __future__ import annotations

from typing import Any

from ..store import repo
from ..store.db import Database


class ReviewQueue:
    def __init__(self, db: Database) -> None:
        self.db = db

    def conflicts(self) -> list[dict[str, Any]]:
        conn = self.db.reader()
        _v, schema = repo.active_schema(conn)
        rows = conn.execute(
            "SELECT c.subject_id, c.predicate, e.type FROM claims c JOIN entities e ON e.id = c.subject_id "
            "WHERE c.kind = 'attribute' AND c.status != 'rejected' AND e.status NOT IN ('merged','rejected') "
            "GROUP BY c.subject_id, c.predicate HAVING COUNT(DISTINCT c.value) > 1"
        ).fetchall()
        out = []
        for r in rows:
            attr = schema.attribute(r["type"], r["predicate"])
            if attr is None or attr.multi:
                continue
            claims = repo.query_claims(conn, entity_id=r["subject_id"], predicate=r["predicate"],
                                       status=["proposed", "verified"])
            claims = [c for c in claims if c.subject_id == r["subject_id"]]
            if not any(c.status.value == "proposed" for c in claims):
                continue  # all verified: the user already decided both are true over time
            out.append({"subject_id": r["subject_id"], "predicate": r["predicate"],
                        "claims": [c.model_dump(mode="json") for c in claims]})
        return out

    def queue(self, limit: int = 100, max_confidence: float = 0.75) -> dict[str, Any]:
        conn = self.db.reader()
        conflicts = self.conflicts()
        in_conflict = {c["id"] for grp in conflicts for c in grp["claims"]}
        flagged = repo.query_claims(conn, needs_review=True, limit=limit)
        proposed = [c for c in repo.query_claims(conn, status=["proposed"], max_confidence=max_confidence,
                                                  order="confidence", limit=limit)
                    if c.id not in in_conflict]
        ids = {x for c in [*flagged, *proposed] for x in (c.subject_id, c.object_id) if x}
        ids |= {grp["subject_id"] for grp in conflicts}
        suggestions = [dict(r) for r in conn.execute(
            "SELECT * FROM ix.merge_suggestions WHERE status = 'open' ORDER BY score DESC LIMIT ?", (limit,))]
        live = repo.get_entities(conn, [x for s in suggestions for x in (s["entity_a"], s["entity_b"])])
        suggestions = [s for s in suggestions
                       if all(live.get(x) and live[x].status.value not in ("merged", "rejected")
                              for x in (s["entity_a"], s["entity_b"]))]
        ids |= {x for s in suggestions for x in (s["entity_a"], s["entity_b"])}
        issues = [{**dict(r), "raw": None} for r in conn.execute(
            "SELECT i.*, s.path FROM ix.extraction_issues i LEFT JOIN sources s ON s.id = i.source_id "
            "ORDER BY i.created_at DESC LIMIT ?", (limit,))]
        entities = repo.get_entities(conn, list(ids))
        total = conn.execute("SELECT COUNT(*) FROM claims WHERE status = 'proposed'").fetchone()[0]
        return {
            "conflicts": conflicts,
            "flagged": [c.model_dump(mode="json") for c in flagged],
            "proposed": [c.model_dump(mode="json") for c in proposed],
            "merge_suggestions": suggestions,
            "extraction_issues": issues,
            "entities": {k: v.model_dump(mode="json") for k, v in entities.items()},
            "total_proposed": total,
        }

    def dismiss_suggestion(self, suggestion_id: str) -> None:
        with self.db.write() as conn:
            conn.execute("UPDATE ix.merge_suggestions SET status = 'dismissed' WHERE id = ?", (suggestion_id,))

    def dismiss_issue(self, issue_id: str) -> None:
        with self.db.write() as conn:
            conn.execute("DELETE FROM ix.extraction_issues WHERE id = ?", (issue_id,))

