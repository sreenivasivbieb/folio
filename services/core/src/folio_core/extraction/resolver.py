"""Entity resolution: candidate (name, type) -> entity id.

Conservative by design (risk: wrong merges). With an open schema the same thing may be typed
differently ("Person" vs "Teacher"), so the *name* is the strong signal:

* exact alias match of a live entity of the same type -> link to it;
* alias of a *rejected* entity of that type -> drop the candidate (the user said it is not real);
* exactly one live entity with that name (any type, except generic Documents) -> link to it;
* otherwise create a new ``auto`` entity and, if a similar name exists, record a merge
  *suggestion* for the review queue. Merges are never forced.
"""

from __future__ import annotations

from ..domain.ids import new_id
from ..domain.models import EntityStatus
from ..domain.rules import normalize_name
from ..domain.schema import canonical_type
from ..knowledge import KnowledgeService
from ..ledger import Tx
from ..providers.embeddings.base import Embedder
from ..store.index_db import IndexDB, utcnow

SUGGEST_THRESHOLD = 0.82


def name_overlap(a: str, b: str) -> bool:
    """True when one normalized name is the other's words in order ("acme" ~ "acme corp") or an
    abbreviation word by word ("acme corp" ~ "acme corporation"). Word-based, so "ai" never
    matches "air"."""
    wa, wb = a.split(), b.split()
    if not wa or not wb or len(a) < 3 or len(b) < 3:
        return False
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    n = len(short)
    if any(long_[i:i + n] == short for i in range(len(long_) - n + 1)):
        return True
    return len(wa) == len(wb) and all(x.startswith(y) or y.startswith(x) for x, y in zip(wa, wb, strict=True))


class EntityResolver:
    def __init__(self, knowledge: KnowledgeService, embedder: Embedder, index: IndexDB) -> None:
        self.knowledge = knowledge
        self.embedder = embedder
        self.index = index

    def resolve(self, tx: Tx, name: str, entity_type: str, actor: str, known_types: list[str]) -> str | None:
        norm = normalize_name(name)
        if not norm:
            return None
        etype = canonical_type(entity_type, known_types)
        rows = tx.find("entities", {"aliases.normalized": norm, "status": {"$ne": "merged"}})
        same = [r for r in rows if r["type"].lower() == etype.lower()]
        if any(r["status"] == EntityStatus.REJECTED for r in same):
            return None
        live_same = [r for r in same if r["status"] != EntityStatus.REJECTED]
        if live_same:
            live_same.sort(key=lambda r: (r["status"] != EntityStatus.VERIFIED, r["created_at"]))
            return live_same[0]["id"]
        live_other = [r for r in rows if r["status"] != EntityStatus.REJECTED and r["type"] != "Document"]
        if etype != "Document" and len(live_other) == 1:
            return live_other[0]["id"]
        if live_other and etype == "Document":
            return None  # never shadow a typed entity with a generic Document
        row = self.knowledge.create_entity_tx(tx, etype, name, actor=actor, status=EntityStatus.AUTO)
        if row["type"] not in known_types:
            known_types.append(row["type"])
        self._suggest_merges(tx, row["id"], name, row["type"])
        return row["id"]

    def _suggest_merges(self, tx: Tx, entity_id: str, name: str, entity_type: str) -> None:
        candidates = tx.find("entities", {"type": entity_type, "status": {"$in": ["auto", "verified"]},
                                          "_id": {"$ne": entity_id}}, limit=500)
        if not candidates:
            return
        vecs = self.embedder.embed([name] + [c["name"] for c in candidates])
        sims = vecs[1:] @ vecs[0]
        norm = normalize_name(name)
        rows = []
        for c, sim in zip(candidates, sims, strict=True):
            other = normalize_name(c["name"])
            contained = name_overlap(norm, other)
            score = max(float(sim), 0.9 if contained else 0.0)
            if score >= SUGGEST_THRESHOLD:
                a, b = sorted([entity_id, c["id"]])
                rows.append((new_id("group"), a, b, round(score, 3),
                             "names overlap" if contained else "similar names", utcnow()))
        if rows:
            with self.index.write() as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO merge_suggestions(id, entity_a, entity_b, score, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)", rows)
