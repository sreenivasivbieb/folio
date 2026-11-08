"""Entity card (FR-5): every data point about an entity, grouped by predicate, each with the
evidence that opens its source at the exact page or timestamp."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..domain.errors import NotFound
from ..domain.schema import MENTIONS, REPRESENTED_BY
from ..store import repo
from ..store.mongo import KnowledgeDB
from .search import HybridSearch


class EntityCards:
    def __init__(self, kdb: KnowledgeDB, search: HybridSearch) -> None:
        self.kdb = kdb
        self.search = search

    def card(self, entity_id: str, passages: int = 5) -> dict[str, Any]:
        entity_id = repo.resolve_merged(self.kdb, entity_id)
        entity = repo.get_entity(self.kdb, entity_id)
        if entity is None:
            raise NotFound(f"entity {entity_id} not found")
        claims = repo.claims_for_entity(self.kdb, entity_id)
        related = repo.get_entities(self.kdb, [x for c in claims for x in (c.subject_id, c.object_id) if x])
        source_ids = [e.source_id for c in claims for e in c.evidence if e.source_id]
        source_ids += [c.value for c in claims if c.predicate == REPRESENTED_BY and isinstance(c.value, str)]
        sources = repo.get_sources(self.kdb, source_ids)

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        files: dict[str, dict[str, Any]] = {}
        cited_chunks: set[str] = set()
        for c in claims:
            outgoing = c.subject_id == entity_id
            if c.predicate == MENTIONS and outgoing:
                key = "mentions"
            elif c.predicate == MENTIONS:
                key = "mentioned in"
            elif c.predicate == REPRESENTED_BY:
                key = "file"
            else:
                key = c.predicate if outgoing else f"{c.predicate} (incoming)"
            groups[key].append({**c.model_dump(mode="json"), "direction": "out" if outgoing else "in"})
            for ev in c.evidence:
                if ev.chunk_id:
                    cited_chunks.add(ev.chunk_id)
                src = sources.get(ev.source_id or "")
                if src and src.id not in files:
                    files[src.id] = {"id": src.id, "path": src.path, "kind": src.kind.value}
            if c.predicate == REPRESENTED_BY and isinstance(c.value, str) and c.value in sources:
                src = sources[c.value]
                files[src.id] = {"id": src.id, "path": src.path, "kind": src.kind.value}

        # Passages that mention the entity but have no extracted claim yet (recall safety net).
        names = " ".join(dict.fromkeys([entity.name, *entity.aliases]))
        extra = [h for h in self.search.search(names, k=passages * 3) if h["chunk_id"] not in cited_chunks]
        counts = {
            "verified": sum(c.status.value == "verified" for c in claims),
            "proposed": sum(c.status.value == "proposed" for c in claims),
            "rejected": sum(c.status.value == "rejected" for c in claims),
        }
        return {
            "entity": entity.model_dump(mode="json"),
            "groups": dict(groups),
            "related": {k: {"id": v.id, "name": v.name, "type": v.type, "status": v.status.value}
                        for k, v in related.items()},
            "files": list(files.values()),
            "passages": extra[:passages],
            "counts": counts,
        }
