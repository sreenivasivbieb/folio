"""Projections of the claim table into the four views (proposal: "Multi-view UI").

All four read the same rows, so an edit anywhere shows everywhere (FR-6):

* graph     — entities as nodes, relation claims as edges
* timeline  — dated claims for one entity
* swimlane  — dated claims grouped by entity or by type along time
* table     — every claim for an entity or filter, with the entities they mention
"""

from __future__ import annotations

from typing import Any

from ..domain.models import Claim
from ..domain.schema import MENTIONS
from ..store import repo
from ..store.db import Database


def _entity_node(e: Any, degree: int = 0) -> dict[str, Any]:
    return {"id": e.id, "name": e.name, "type": e.type, "status": e.status.value, "degree": degree}


def _claim_view(c: Claim) -> dict[str, Any]:
    return c.model_dump(mode="json")


class Views:
    def __init__(self, db: Database) -> None:
        self.db = db

    def graph(self, entity_id: str | None = None, depth: int = 2, limit: int = 2000,
              include_rejected: bool = False, include_mentions: bool = False,
              types: list[str] | None = None) -> dict[str, Any]:
        conn = self.db.reader()
        status = "" if include_rejected else "AND c.status != 'rejected'"
        mentions = "" if include_mentions else f"AND c.predicate != '{MENTIONS}'"
        if entity_id:
            entity_id = repo.resolve_merged(conn, entity_id)
            # Graph traversal = recursive query over the claim table (no graph database needed).
            ids = [r[0] for r in conn.execute(
                f"""
                WITH RECURSIVE hood(id, depth) AS (
                  SELECT ?, 0
                  UNION
                  SELECT CASE WHEN c.subject_id = h.id THEN c.object_id ELSE c.subject_id END, h.depth + 1
                  FROM claims c JOIN hood h ON (c.subject_id = h.id OR c.object_id = h.id)
                  WHERE c.kind = 'relation' {status} {mentions} AND h.depth < ?
                )
                SELECT id FROM hood GROUP BY id ORDER BY MIN(depth) LIMIT ?
                """, (entity_id, depth, limit),
            )]
        else:
            ids = [r[0] for r in conn.execute(
                "SELECT e.id FROM entities e WHERE e.status NOT IN ('merged', 'rejected') "
                "ORDER BY (SELECT COUNT(*) FROM claims c WHERE c.subject_id = e.id OR c.object_id = e.id) DESC "
                "LIMIT ?", (limit,),
            )]
        entities = repo.get_entities(conn, ids)
        if types:
            entities = {k: v for k, v in entities.items() if v.type in types}
        if not include_rejected:
            entities = {k: v for k, v in entities.items() if v.status.value != "rejected"}
        keys = list(entities)
        edges: list[dict[str, Any]] = []
        degree: dict[str, int] = dict.fromkeys(keys, 0)
        for i in range(0, len(keys), 400):
            batch = keys[i : i + 400]
            marks = ",".join("?" * len(batch))
            for r in conn.execute(
                f"SELECT * FROM claims c WHERE c.kind = 'relation' {status} {mentions} "
                f"AND c.subject_id IN ({marks})", batch,
            ):
                if r["object_id"] in entities:
                    edges.append({"id": r["id"], "source": r["subject_id"], "target": r["object_id"],
                                  "predicate": r["predicate"], "status": r["status"],
                                  "confidence": r["confidence"]})
                    degree[r["subject_id"]] += 1
                    degree[r["object_id"]] += 1
        nodes = [_entity_node(e, degree[e.id]) for e in entities.values()
                 if include_mentions or e.type != "Document" or degree[e.id] or e.id == entity_id]
        return {"nodes": nodes, "edges": edges}

    def timeline(self, entity_id: str, include_rejected: bool = False) -> dict[str, Any]:
        conn = self.db.reader()
        entity_id = repo.resolve_merged(conn, entity_id)
        claims = [c for c in repo.claims_for_entity(conn, entity_id, include_rejected)
                  if c.valid_from]
        others = repo.get_entities(conn, [x for c in claims for x in (c.subject_id, c.object_id) if x])
        return {
            "entity": repo.get_entity(conn, entity_id),
            "items": [_claim_view(c) for c in sorted(claims, key=lambda c: c.valid_from or "")],
            "entities": {k: _entity_node(v) for k, v in others.items()},
        }

    def swimlane(self, group_by: str = "entity", entity_ids: list[str] | None = None,
                 types: list[str] | None = None, include_rejected: bool = False,
                 limit: int = 2000) -> dict[str, Any]:
        conn = self.db.reader()
        where = ["c.valid_from IS NOT NULL", "e.status NOT IN ('merged', 'rejected')"]
        args: list[Any] = []
        if not include_rejected:
            where.append("c.status != 'rejected'")
        if entity_ids:
            where.append(f"c.subject_id IN ({','.join('?' * len(entity_ids))})")
            args += entity_ids
        if types:
            where.append(f"e.type IN ({','.join('?' * len(types))})")
            args += types
        rows = conn.execute(
            f"SELECT c.* FROM claims c JOIN entities e ON e.id = c.subject_id "
            f"WHERE {' AND '.join(where)} ORDER BY c.valid_from LIMIT ?", [*args, limit],
        ).fetchall()
        claims = repo.hydrate_claims(conn, rows)
        ents = repo.get_entities(conn, [x for c in claims for x in (c.subject_id, c.object_id) if x])
        lanes: dict[str, dict[str, Any]] = {}
        for c in claims:
            subj = ents[c.subject_id]
            key, title = (subj.id, subj.name) if group_by == "entity" else (subj.type, subj.type)
            lane = lanes.setdefault(key, {"id": key, "title": title, "type": subj.type, "items": []})
            lane["items"].append(_claim_view(c))
        return {"group_by": group_by, "lanes": list(lanes.values()),
                "entities": {k: _entity_node(v) for k, v in ents.items()}}

    def table(self, **filters: Any) -> dict[str, Any]:
        conn = self.db.reader()
        claims = repo.query_claims(conn, **filters)
        ents = repo.get_entities(conn, [x for c in claims for x in (c.subject_id, c.object_id) if x])
        return {"claims": [_claim_view(c) for c in claims],
                "entities": {k: _entity_node(v) for k, v in ents.items()}}
