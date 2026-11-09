"""Hybrid retrieval: FTS5 keyword ranking + vector similarity, fused with Reciprocal Rank Fusion."""

from __future__ import annotations

import re
from typing import Any

from ..providers.embeddings.base import Embedder
from ..store import repo
from ..store.index_db import IndexDB, loads
from ..store.local import KnowledgeDB
from ..store.vectors import VectorIndex

RRF_K = 60
_TOKEN = re.compile(r"\w+", re.UNICODE)


def fts_query(q: str) -> str | None:
    tokens = [t for t in _TOKEN.findall(q) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in tokens) or None


class HybridSearch:
    def __init__(self, index: IndexDB, kdb: KnowledgeDB, embedder: Embedder, vectors: VectorIndex) -> None:
        self.index = index
        self.kdb = kdb
        self.embedder = embedder
        self.vectors = vectors

    def search(self, q: str, k: int = 20, source_ids: list[str] | None = None) -> list[dict[str, Any]]:
        conn = self.index.reader()
        pool = max(k * 4, 50)
        ranked: dict[int, float] = {}

        if match := fts_query(q):
            rows = conn.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
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
            f"SELECT rowid AS rid, id, source_id, text, locator FROM chunks WHERE rowid IN ({marks})", rowids,
        ).fetchall()
        by_id = {r["rid"]: r for r in rows}
        sources = repo.get_sources(self.kdb, [r["source_id"] for r in rows])
        hits = []
        for rowid in rowids:
            r = by_id.get(rowid)
            src = sources.get(r["source_id"]) if r is not None else None
            if r is None or src is None or src.status.value in repo.HIDDEN_SOURCE_STATUSES:
                continue
            if source_ids and r["source_id"] not in source_ids:
                continue
            hits.append({
                "chunk_id": r["id"], "source_id": r["source_id"], "path": src.path, "kind": src.kind.value,
                "text": r["text"], "locator": loads(r["locator"]), "score": round(ranked[rowid], 5),
            })
            if len(hits) >= k:
                break
        return hits
