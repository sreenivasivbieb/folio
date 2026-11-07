from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..providers.embeddings.base import Embedder
from ..store.db import Database, loads


@dataclass(frozen=True)
class GazetteerEntry:
    alias: str
    normalized: str
    entity_id: str
    entity_type: str
    entity_name: str
    status: str  # rejected entries are kept so their names are not re-proposed


class CorrectionStore:
    def __init__(self, db: Database, embedder: Embedder) -> None:
        self.db = db
        self.embedder = embedder

    def gazetteer(self, include_rejected: bool = False) -> list[GazetteerEntry]:
        """Every known name/alias of every live entity, longest first (for greedy matching)."""
        statuses = "('auto', 'verified', 'rejected')" if include_rejected else "('auto', 'verified')"
        rows = self.db.reader().execute(
            "SELECT a.alias, a.normalized, e.id, e.type, e.name, e.status FROM aliases a "
            f"JOIN entities e ON e.id = a.entity_id WHERE e.status IN {statuses}"
        ).fetchall()
        entries = [GazetteerEntry(*r) for r in rows]
        return sorted(entries, key=lambda e: -len(e.normalized))

    def vocabulary_prompt(self, limit: int = 80) -> str | None:
        """Verified names, most-used first, as an ASR initial prompt ("Priya, Acme Corp, ...")."""
        rows = self.db.reader().execute(
            "SELECT a.alias FROM aliases a JOIN entities e ON e.id = a.entity_id "
            "WHERE e.status = 'verified' GROUP BY a.alias "
            "ORDER BY (SELECT COUNT(*) FROM claims c WHERE c.subject_id = e.id OR c.object_id = e.id) DESC "
            "LIMIT ?", (limit,),
        ).fetchall()
        names = [r[0] for r in rows]
        return ("Names: " + ", ".join(names) + ".") if names else None

    def _examples(self, status: str, extractor_kinds: tuple[str, ...], text: str, k: int,
                  pool: int = 200) -> list[dict[str, Any]]:
        marks = ",".join("?" * len(extractor_kinds))
        rows = self.db.reader().execute(
            "SELECT c.predicate, c.value, c.kind, s.name AS subject, s.type AS subject_type, "
            "o.name AS object, o.type AS object_type, ev.quote "
            "FROM claims c JOIN entities s ON s.id = c.subject_id "
            "LEFT JOIN entities o ON o.id = c.object_id "
            "JOIN evidence ev ON ev.claim_id = c.id AND ev.source_id IS NOT NULL "
            f"WHERE c.status = ? AND json_extract(c.extractor, '$.kind') IN ({marks}) "
            "GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?",
            (status, *extractor_kinds, pool),
        ).fetchall()
        if not rows:
            return []
        quotes = [r["quote"] for r in rows]
        sims = self.embedder.embed(quotes) @ self.embedder.embed([text])[0]
        best = np.argsort(-sims)[:k]
        out = []
        for i in best:
            r = rows[int(i)]
            out.append({
                "quote": r["quote"], "subject": r["subject"], "subject_type": r["subject_type"],
                "predicate": r["predicate"], "object": r["object"], "object_type": r["object_type"],
                "value": loads(r["value"]),
            })
        return out

    def few_shot(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        """Most similar verified claims (by evidence text) — positive examples for the prompt."""
        return self._examples("verified", ("model", "user", "voice"), text, k)

    def negatives(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        """Most similar rejected model claims — 'do not propose' examples."""
        return self._examples("rejected", ("model",), text, k)

    def acceptance(self) -> list[dict[str, Any]]:
        """Acceptance rate of model-proposed claims per entity type per ISO week (release metric)."""
        rows = self.db.reader().execute(
            "SELECT e.type, strftime('%Y-W%W', c.created_at) AS week, "
            "SUM(c.status = 'verified') AS verified, SUM(c.status = 'rejected') AS rejected, "
            "SUM(c.status = 'proposed') AS proposed "
            "FROM claims c JOIN entities e ON e.id = c.subject_id "
            "WHERE json_extract(c.extractor, '$.kind') = 'model' GROUP BY e.type, week ORDER BY week"
        ).fetchall()
        out = []
        for r in rows:
            decided = (r["verified"] or 0) + (r["rejected"] or 0)
            out.append({**dict(r), "rate": (r["verified"] / decided) if decided else None})
        return out
