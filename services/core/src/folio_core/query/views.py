"""Projections of the claims collection into the four views (proposal: "Multi-view UI").

All four read the same documents, so an edit anywhere shows everywhere (FR-6):

* graph     — entities as nodes, relation claims as edges (breadth-first expansion)
* timeline  — dated claims for one entity
* swimlane  — dated claims grouped by entity or by type along time
* table     — every claim for an entity or filter, with the entities they mention
"""

from __future__ import annotations

from typing import Any

from ..domain.models import Claim
from ..domain.schema import MENTIONS
from ..store import repo
from ..store.local import KnowledgeDB


def _entity_node(e: Any, degree: int = 0) -> dict[str, Any]:
    return {"id": e.id, "name": e.name, "type": e.type, "status": e.status.value, "degree": degree}


def _claim_view(c: Claim) -> dict[str, Any]:
    return c.model_dump(mode="json")


class Views:
    def __init__(self, kdb: KnowledgeDB) -> None:
        self.kdb = kdb

    def _relation_filter(self, include_rejected: bool, include_mentions: bool) -> dict[str, Any]:
        q: dict[str, Any] = {"kind": "relation"}
        if not include_rejected:
            q["status"] = {"$ne": "rejected"}
        if not include_mentions:
            q["predicate"] = {"$ne": MENTIONS}
        return q

    def graph(self, entity_id: str | None = None, depth: int = 2, limit: int = 2000,
              include_rejected: bool = False, include_mentions: bool = False,
              types: list[str] | None = None) -> dict[str, Any]:
        rel = self._relation_filter(include_rejected, include_mentions)
        if entity_id:
            entity_id = repo.resolve_merged(self.kdb, entity_id)
            ids, frontier = {entity_id}, {entity_id}
            for _ in range(depth):  # breadth-first neighbourhood
                if not frontier or len(ids) >= limit:
                    break
                nxt: set[str] = set()
                for c in self.kdb["claims"].find({**rel, "$or": [{"subject_id": {"$in": list(frontier)}},
                                                                 {"object_id": {"$in": list(frontier)}}]},
                                                 {"subject_id": 1, "object_id": 1}):
                    nxt |= {c["subject_id"], c["object_id"]}
                frontier = nxt - ids
                ids |= nxt
            id_list = list(ids)[:limit]
        else:
            q: dict[str, Any] = {"status": {"$nin": ["merged", "rejected"]}}
            docs = list(self.kdb["entities"].find(q, {"_id": 1}).limit(limit * 3))
            counts = repo.claim_counts(self.kdb, [d["_id"] for d in docs])
            id_list = sorted((d["_id"] for d in docs), key=lambda i: -counts.get(i, 0))[:limit]
        entities = repo.get_entities(self.kdb, id_list)
        entities = {k: v for k, v in entities.items()
                    if (include_rejected or v.status.value != "rejected") and v.status.value != "merged"
                    and (not types or v.type in types)}
        edges: list[dict[str, Any]] = []
        degree = dict.fromkeys(entities, 0)
        keys = list(entities)
        for c in self.kdb["claims"].find({**rel, "subject_id": {"$in": keys}, "object_id": {"$in": keys}}):
            edges.append({"id": c["_id"], "source": c["subject_id"], "target": c["object_id"],
                          "predicate": c["predicate"], "status": c["status"], "confidence": c["confidence"]})
            degree[c["subject_id"]] += 1
            degree[c["object_id"]] += 1
        nodes = [_entity_node(e, degree[e.id]) for e in entities.values()
                 if include_mentions or e.type != "Document" or degree[e.id] or e.id == entity_id]
        return {"nodes": nodes, "edges": edges}

    def timeline(self, entity_id: str, include_rejected: bool = False) -> dict[str, Any]:
        entity_id = repo.resolve_merged(self.kdb, entity_id)
        claims = [c for c in repo.claims_for_entity(self.kdb, entity_id, include_rejected) if c.valid_from]
        others = repo.get_entities(self.kdb, [x for c in claims for x in (c.subject_id, c.object_id) if x])
        return {
            "entity": repo.get_entity(self.kdb, entity_id),
            "items": [_claim_view(c) for c in sorted(claims, key=lambda c: c.valid_from or "")],
            "entities": {k: _entity_node(v) for k, v in others.items()},
        }

    def swimlane(self, group_by: str = "entity", entity_ids: list[str] | None = None,
                 types: list[str] | None = None, include_rejected: bool = False,
                 limit: int = 2000) -> dict[str, Any]:
        q: dict[str, Any] = {"valid_from": {"$ne": None}}
        if not include_rejected:
            q["status"] = {"$ne": "rejected"}
        if entity_ids:
            q["subject_id"] = {"$in": entity_ids}
        claims = [repo.claim_from_doc(d) for d in self.kdb["claims"].find(q).sort("valid_from", 1).limit(limit)]
        ents = repo.get_entities(self.kdb, [x for c in claims for x in (c.subject_id, c.object_id) if x])
        lanes: dict[str, dict[str, Any]] = {}
        for c in claims:
            subj = ents.get(c.subject_id)
            if subj is None or subj.status.value in ("merged", "rejected") or (types and subj.type not in types):
                continue
            key, title = (subj.id, subj.name) if group_by == "entity" else (subj.type, subj.type)
            lane = lanes.setdefault(key, {"id": key, "title": title, "type": subj.type, "items": []})
            lane["items"].append(_claim_view(c))
        return {"group_by": group_by, "lanes": list(lanes.values()),
                "entities": {k: _entity_node(v) for k, v in ents.items()}}

    def table(self, **filters: Any) -> dict[str, Any]:
        claims = repo.query_claims(self.kdb, **filters)
        ents = repo.get_entities(self.kdb, [x for c in claims for x in (c.subject_id, c.object_id) if x])
        return {"claims": [_claim_view(c) for c in claims],
                "entities": {k: _entity_node(v) for k, v in ents.items()}}
