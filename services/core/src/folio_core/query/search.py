"""Hybrid retrieval: FTS5 keyword ranking + vector similarity, fused with Reciprocal Rank Fusion."""

from __future__ import annotations

import re
from typing import Any

from ..providers.embeddings.base import Embedder
from ..store.db import Database, loads
from ..store.vectors import VectorIndex

RRF_K = 60
_TOKEN = re.compile(r"\w+", re.UNICODE)


def fts_query(q: str) -> str | None:
    tokens = [t for t in _TOKEN.findall(q) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in tokens) or None


class HybridSearch:
    def __init__(self, db: Database, embedder: Embedder, vectors: VectorIndex) -> None:
        self.db = db
        self.embedder = embedder
        self.vectors = vectors

    def search(self, q: str, k: int = 20, source_ids: list[str] | None = None) -> list[dict[str, Any]]:
        conn = self.db.reader()
        pool = max(k * 4, 50)
        ranked: dict[int, float] = {}

        if match := fts_query(q):
            rows = conn.execute(
                "SELECT rowid FROM ix.chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
                (match, pool),
            ).fetchall()
            for rank, r in enumerate(rows):
                ranked[r[0]] = ranked.get(r[0], 0) + 1 / (RRF_K + rank + 1)

        qvec = self.embedder.embed([q])[0]
        for rank, (rowid, _sim) in enumerate(self.vectors.search(qvec, pool)):
            ranked[rowid] = ranked.get(rowid, 0) + 1 / (RRF_K + rank + 1)

        if not ranked:
            return []
        rowids = sorted(ranked, key=lambda r: -ranked[r])
        marks = ",".join("?" * len(rowids))
        rows = conn.execute(
            f"SELECT c.rowid AS rid, c.id, c.source_id, c.text, c.locator, s.path, s.kind "
            f"FROM ix.chunks c JOIN sources s ON s.id = c.source_id "
            f"WHERE c.rowid IN ({marks}) AND s.status != 'forgotten'", rowids,
        ).fetchall()
        by_id = {r["rid"]: r for r in rows}
        hits = []
        for rowid in rowids:
            r = by_id.get(rowid)
            if r is None or (source_ids and r["source_id"] not in source_ids):
                continue
            hits.append({
                "chunk_id": r["id"], "source_id": r["source_id"], "path": r["path"], "kind": r["kind"],
                "text": r["text"], "locator": loads(r["locator"]), "score": round(ranked[rowid], 5),
            })
            if len(hits) >= k:
                break
        return hits
