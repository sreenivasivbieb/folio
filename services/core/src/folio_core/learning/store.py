from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..providers.embeddings.base import Embedder
from ..store.mongo import KnowledgeDB


@dataclass(frozen=True)
class GazetteerEntry:
    alias: str
    normalized: str
    entity_id: str
    entity_type: str
    entity_name: str
    status: str  # rejected entries are kept so their names are not re-proposed


class CorrectionStore:
    def __init__(self, kdb: KnowledgeDB, embedder: Embedder) -> None:
        self.kdb = kdb
        self.embedder = embedder

    def gazetteer(self, include_rejected: bool = False) -> list[GazetteerEntry]:
        """Every known name/alias of every live entity, longest first (for greedy matching)."""
        statuses = ["auto", "verified", "rejected"] if include_rejected else ["auto", "verified"]
        entries = [
            GazetteerEntry(a["alias"], a["normalized"], d["_id"], d["type"], d["name"], d["status"])
            for d in self.kdb["entities"].find({"status": {"$in": statuses}}, {"aliases": 1, "type": 1, "name": 1, "status": 1})
            for a in d.get("aliases", [])
        ]
        return sorted(entries, key=lambda e: -len(e.normalized))

    def vocabulary_prompt(self, limit: int = 80) -> str | None:
        """Verified names as an ASR initial prompt ("Names: Priya, Acme Corp, ...")."""
        names: list[str] = []
        for d in self.kdb["entities"].find({"status": "verified", "type": {"$ne": "Document"}},
                                           {"aliases": 1}).sort("updated_at", -1).limit(limit):
            names += [a["alias"] for a in d.get("aliases", [])]
        names = list(dict.fromkeys(names))[:limit]
        return ("Names: " + ", ".join(names) + ".") if names else None

    def _examples(self, status: str, kinds: list[str], text: str, k: int, pool: int = 200) -> list[dict[str, Any]]:
        docs = list(self.kdb["claims"].find(
            {"status": status, "extractor.kind": {"$in": kinds}, "evidence.source_id": {"$ne": None}},
        ).sort("updated_at", -1).limit(pool))
        docs = [d for d in docs if any(e.get("source_id") for e in d.get("evidence", []))]
        if not docs:
            return []
        ents = {e["_id"]: e for e in self.kdb["entities"].find(
            {"_id": {"$in": list({x for d in docs for x in (d["subject_id"], d.get("object_id")) if x})}},
            {"name": 1, "type": 1})}
        quotes = [next(e["quote"] for e in d["evidence"] if e.get("source_id")) for d in docs]
        sims = self.embedder.embed(quotes) @ self.embedder.embed([text])[0]
        out = []
        for i in np.argsort(-sims)[:k]:
            d = docs[int(i)]
            s, o = ents.get(d["subject_id"], {}), ents.get(d.get("object_id") or "", {})
            out.append({"quote": quotes[int(i)], "subject": s.get("name"), "subject_type": s.get("type"),
                        "predicate": d["predicate"], "object": o.get("name"), "object_type": o.get("type"),
                        "value": d.get("value")})
        return out

    def few_shot(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        """Most similar verified claims (by evidence text) — positive examples for the prompt."""
        return self._examples("verified", ["model", "user", "voice"], text, k)

    def negatives(self, text: str, k: int = 3) -> list[dict[str, Any]]:
        """Most similar rejected model claims — 'do not propose' examples."""
        return self._examples("rejected", ["model"], text, k)

    def acceptance(self) -> list[dict[str, Any]]:
        """Acceptance rate of model-proposed claims per entity type per ISO week (release metric)."""
        rows = list(self.kdb["claims"].aggregate([
            {"$match": {"extractor.kind": "model"}},
            {"$lookup": {"from": "entities", "localField": "subject_id", "foreignField": "_id", "as": "s"}},
            {"$unwind": "$s"},
            {"$group": {
                "_id": {"type": "$s.type", "week": {"$dateToString": {"format": "%G-W%V", "date": {"$dateFromString": {"dateString": "$created_at"}}}}},
                "verified": {"$sum": {"$cond": [{"$eq": ["$status", "verified"]}, 1, 0]}},
                "rejected": {"$sum": {"$cond": [{"$eq": ["$status", "rejected"]}, 1, 0]}},
                "proposed": {"$sum": {"$cond": [{"$eq": ["$status", "proposed"]}, 1, 0]}},
            }},
            {"$sort": {"_id.week": 1}},
        ]))
        out = []
        for r in rows:
            decided = r["verified"] + r["rejected"]
            out.append({"type": r["_id"]["type"], "week": r["_id"]["week"], "verified": r["verified"],
                        "rejected": r["rejected"], "proposed": r["proposed"],
                        "rate": r["verified"] / decided if decided else None})
        return out
