"""Review queue: the riskiest facts first, so a few minutes of review covers what matters.

Order: conflicts (same subject + single-valued attribute, different values) -> claims flagged for
review (e.g. their only source was forgotten) -> proposed claims by ascending confidence.
Merge suggestions and failed extractions are listed alongside. Document "mentions" (string
matches, always correct) are not review work and are left out.
"""

from __future__ import annotations

from typing import Any

from ..domain.schema import MENTIONS, REPRESENTED_BY, SchemaDef
from ..store import repo
from ..store.index_db import IndexDB
from ..store.mongo import KnowledgeDB

NOT_REVIEW_WORK = [MENTIONS, REPRESENTED_BY]
_DATE_SUFFIXES = ("_on", "_date", "_at", "_since", "_until")


def single_valued(schema: SchemaDef, entity_type: str, predicate: str) -> bool:
    """Open schema: hints decide when they exist; otherwise date-like attributes are single."""
    hint = schema.attribute(entity_type, predicate)
    if hint is not None:
        return not hint.multi
    return predicate.endswith(_DATE_SUFFIXES)


class ReviewQueue:
    def __init__(self, kdb: KnowledgeDB, index: IndexDB) -> None:
        self.kdb = kdb
        self.index = index

    def conflicts(self) -> list[dict[str, Any]]:
        _v, schema = repo.active_schema(self.kdb)
        groups = list(self.kdb["claims"].aggregate([
            {"$match": {"kind": "attribute", "status": {"$ne": "rejected"}, "predicate": {"$nin": NOT_REVIEW_WORK + ["mentioned"]}}},
            {"$group": {"_id": {"s": "$subject_id", "p": "$predicate"}, "values": {"$addToSet": "$value"},
                        "ids": {"$push": "$_id"}, "proposed": {"$sum": {"$cond": [{"$eq": ["$status", "proposed"]}, 1, 0]}}}},
            {"$match": {"values.1": {"$exists": True}, "proposed": {"$gt": 0}}},
        ]))
        ents = repo.get_entities(self.kdb, [g["_id"]["s"] for g in groups])
        out = []
        for g in groups:
            e = ents.get(g["_id"]["s"])
            if e is None or e.status.value in ("merged", "rejected") or not single_valued(schema, e.type, g["_id"]["p"]):
                continue
            claims = [repo.claim_from_doc(d) for d in self.kdb["claims"].find({"_id": {"$in": g["ids"]}})]
            out.append({"subject_id": e.id, "predicate": g["_id"]["p"], "claims": [c.model_dump(mode="json") for c in claims]})
        return out

    def queue(self, limit: int = 100, max_confidence: float = 0.75) -> dict[str, Any]:
        conflicts = self.conflicts()
        in_conflict = {c["id"] for grp in conflicts for c in grp["claims"]}
        flagged = repo.query_claims(self.kdb, needs_review=True, limit=limit)
        proposed = [c for c in repo.query_claims(self.kdb, status=["proposed"], max_confidence=max_confidence,
                                                  exclude_predicates=NOT_REVIEW_WORK, order="confidence", limit=limit)
                    if c.id not in in_conflict]
        ids = {x for c in [*flagged, *proposed] for x in (c.subject_id, c.object_id) if x}
        ids |= {grp["subject_id"] for grp in conflicts}
        conn = self.index.reader()
        suggestions = [dict(r) for r in conn.execute(
            "SELECT * FROM merge_suggestions WHERE status = 'open' ORDER BY score DESC LIMIT ?", (limit,))]
        live = repo.get_entities(self.kdb, [x for s in suggestions for x in (s["entity_a"], s["entity_b"])])
        suggestions = [s for s in suggestions
                       if all(live.get(x) and live[x].status.value not in ("merged", "rejected")
                              for x in (s["entity_a"], s["entity_b"]))]
        ids |= {x for s in suggestions for x in (s["entity_a"], s["entity_b"])}
        issues = [{**dict(r), "raw": None, "path": None} for r in conn.execute(
            "SELECT * FROM extraction_issues ORDER BY created_at DESC LIMIT ?", (limit,))]
        paths = repo.get_sources(self.kdb, [i["source_id"] for i in issues])
        for i in issues:
            i["path"] = paths[i["source_id"]].path if i["source_id"] in paths else None
        total = self.kdb["claims"].count_documents({"status": "proposed", "predicate": {"$nin": NOT_REVIEW_WORK}})
        return {
            "conflicts": conflicts,
            "flagged": [c.model_dump(mode="json") for c in flagged],
            "proposed": [c.model_dump(mode="json") for c in proposed],
            "merge_suggestions": suggestions,
            "extraction_issues": issues,
            "entities": {k: v.model_dump(mode="json") for k, v in repo.get_entities(self.kdb, list(ids)).items()},
            "total_proposed": total,
        }

    def dismiss_suggestion(self, suggestion_id: str) -> None:
        with self.index.write() as conn:
            conn.execute("UPDATE merge_suggestions SET status = 'dismissed' WHERE id = ?", (suggestion_id,))

    def dismiss_issue(self, issue_id: str) -> None:
        with self.index.write() as conn:
            conn.execute("DELETE FROM extraction_issues WHERE id = ?", (issue_id,))
