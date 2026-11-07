"""Entity resolution: candidate (name, type) -> entity id.

Conservative by design (risk: wrong merges):
* exact alias match of a live entity -> link to it;
* alias of a *rejected* entity -> drop the candidate (the user said it is not real);
* otherwise create a new ``auto`` entity and, if a similar name exists, record a merge
  *suggestion* for the review queue. Merges are never forced.
"""

from __future__ import annotations

from ..domain.ids import new_id
from ..domain.models import EntityStatus
from ..domain.rules import normalize_name
from ..knowledge import KnowledgeService
from ..ledger import Tx
from ..providers.embeddings.base import Embedder
from ..store.db import utcnow

SUGGEST_THRESHOLD = 0.82


class EntityResolver:
    def __init__(self, knowledge: KnowledgeService, embedder: Embedder) -> None:
        self.knowledge = knowledge
        self.embedder = embedder

    def resolve(self, tx: Tx, name: str, entity_type: str, actor: str) -> str | None:
        norm = normalize_name(name)
        if not norm:
            return None
        rows = tx.conn.execute(
            "SELECT e.id, e.type, e.status FROM aliases a JOIN entities e ON e.id = a.entity_id "
            "WHERE a.normalized = ? AND e.status != 'merged'", (norm,),
        ).fetchall()
        same_type = [r for r in rows if r["type"] == entity_type]
        if any(r["status"] == EntityStatus.REJECTED for r in same_type):
            return None
        live = [r for r in same_type if r["status"] != EntityStatus.REJECTED]
        if live:
            # Prefer a verified entity; ties go to the oldest.
            live.sort(key=lambda r: (r["status"] != EntityStatus.VERIFIED, r["id"]))
            return live[0]["id"]
        other_type = [r for r in rows if r["status"] != EntityStatus.REJECTED]
        if other_type and entity_type == "Document":
            return None  # never shadow a typed entity with a generic Document
        row = self.knowledge.create_entity_tx(tx, entity_type, name, actor=actor,
                                              status=EntityStatus.AUTO)
        self._suggest_merges(tx, row["id"], name, entity_type)
        return row["id"]

    def _suggest_merges(self, tx: Tx, entity_id: str, name: str, entity_type: str) -> None:
        candidates = tx.conn.execute(
            "SELECT id, name FROM entities WHERE type = ? AND status IN ('auto', 'verified') AND id != ? "
            "ORDER BY updated_at DESC LIMIT 500", (entity_type, entity_id),
        ).fetchall()
        if not candidates:
            return
        vecs = self.embedder.embed([name] + [c["name"] for c in candidates])
        sims = vecs[1:] @ vecs[0]
        norm = normalize_name(name)
        for c, sim in zip(candidates, sims, strict=True):
            other = normalize_name(c["name"])
            contained = len(norm) >= 3 and len(other) >= 3 and (norm in other or other in norm)
            score = max(float(sim), 0.9 if contained else 0.0)
            if score >= SUGGEST_THRESHOLD:
                a, b = sorted([entity_id, c["id"]])
                tx.conn.execute(
                    "INSERT OR IGNORE INTO ix.merge_suggestions(id, entity_a, entity_b, score, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id("group"), a, b, round(score, 3),
                     "name contains the other" if contained else "similar names", utcnow()),
                )

