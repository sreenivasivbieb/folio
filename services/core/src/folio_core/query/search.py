"""Hybrid retrieval: FTS5 keyword ranking + vector similarity, fused with Reciprocal Rank Fusion."""

from __future__ import annotations

import json
import re
from typing import Any

from ..domain.schema import REPRESENTED_BY
from ..providers.embeddings.base import Embedder
from ..store import repo
from ..store.index_db import IndexDB, loads
from ..store.local import KnowledgeDB
from ..store.vectors import VectorIndex

RRF_K = 60
_TOKEN = re.compile(r"\w+", re.UNICODE)


def fts_query(q: str) -> str | None:
    """Prefix matching, so a partly typed word already finds passages ("hack" -> hackathon)."""
    tokens = [t for t in _TOKEN.findall(q) if len(t) > 1]
    return " OR ".join(f'"{t}"*' for t in tokens) or None


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


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
        floor = getattr(self.embedder, "min_similarity", 0.0)
        # Nearest neighbours always exist; without a floor every query "matched" random passages.
        close = [(rowid, sim) for rowid, sim in self.vectors.search(qvec, pool) if sim >= floor]
        for rank, (rowid, _sim) in enumerate(close):
            ranked[rowid] = ranked.get(rowid, 0) + 1 / (RRF_K + rank + 1)

        if not ranked:
            return []
        rowids = sorted(ranked, key=lambda r: -ranked[r])
        rows = conn.execute(
            "SELECT rowid AS rid, id, source_id, text, locator FROM chunks "
            "WHERE rowid IN (SELECT value FROM json_each(?))", (json.dumps(rowids),),
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

    def files(self, q: str, entities: list[Any], k: int = 20) -> list[dict[str, Any]]:
        """Files for a topic/name query: files labelled with (or represented by) a matching
        entity, files whose label transcript mentions the words, then file names."""
        q = q.strip()
        if len(q) < 2:
            return []
        found: dict[str, dict[str, Any]] = {}

        def add(source_id: str | None, via: str) -> None:
            if source_id and source_id not in found:
                found[source_id] = {"source_id": source_id, "via": via or "related entity"}

        # 1. Linked through the knowledge graph: "this file is about <topic>".
        ent_ids = [e.id for e in entities]
        names = {e.id: e.name for e in entities}
        if ent_ids:
            claims = list(self.kdb["claims"].find({"$or": [{"subject_id": {"$in": ent_ids}},
                                                            {"object_id": {"$in": ent_ids}}],
                                                   "status": {"$ne": "rejected"}}))
            docs = {c["subject_id"] for c in claims} | {c.get("object_id") for c in claims if c.get("object_id")}
            files_of = {}
            for c in self.kdb["claims"].find({"predicate": REPRESENTED_BY, "subject_id": {"$in": list(docs)},
                                              "status": {"$ne": "rejected"}}):
                files_of.setdefault(c["subject_id"], []).append(c["value"])
            for c in claims:
                hit = names.get(c["subject_id"]) or names.get(c.get("object_id")) or "related entity"
                if c["predicate"] == REPRESENTED_BY:
                    add(c.get("value"), hit)
                for other in (c["subject_id"], c.get("object_id")):
                    for sid in files_of.get(other, []):
                        add(sid, hit)
                for e in c.get("evidence", []):
                    if e.get("label_id"):  # a label said it about this file
                        add(e.get("source_id"), hit)
        words = [w for w in _TOKEN.findall(q.lower()) if len(w) > 1]
        pattern = "".join(f"(?=.*{re.escape(w)})" for w in words)
        # 1b. Descriptions, titles and other values said about a file ("lexsi hackathon video demo").
        if words:
            described = list(self.kdb["claims"].find({"kind": "attribute", "status": {"$ne": "rejected"},
                                                      "value": {"$regex": pattern, "$options": "i"}}).limit(200))
            subjects = list({c["subject_id"] for c in described})
            by_subject: dict[str, list[str]] = {}
            for c in self.kdb["claims"].find({"predicate": REPRESENTED_BY, "subject_id": {"$in": subjects},
                                              "status": {"$ne": "rejected"}}):
                by_subject.setdefault(c["subject_id"], []).append(c["value"])
            for c in described:
                for sid in by_subject.get(c["subject_id"], []):
                    add(sid, f"{c['predicate'].replace('_', ' ')}: {str(c['value'])[:60]}")
        # 2. Label transcripts that mention the words.
        if words:
            for lab in self.kdb["labels"].find({"transcript": {"$regex": pattern, "$options": "i"},
                                                "status": "committed"}).limit(200):
                if lab.get("target_kind") == "source":
                    for sid in lab.get("target_ids", []):
                        add(sid, f"label: {lab['transcript'][:60]}")
        # 3. File names: every typed word, in any order.
        first = words[0] if words else q
        like = "%" + first.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self.kdb._read_guard():
            rows = self.kdb._reader().execute(
                "SELECT id FROM documents WHERE collection = 'sources' AND "
                "json_extract(body, '$.path') LIKE ? ESCAPE '\\' "
                "AND json_extract(body, '$.status') NOT IN ('forgotten', 'removed') LIMIT ?",
                (like, 500)).fetchall()
        for (sid,) in rows:
            add(sid, "file name")
        sources = repo.get_sources(self.kdb, list(found))
        out = []
        for sid, hit in found.items():
            src = sources.get(sid)
            if src is None or src.status.value in repo.HIDDEN_SOURCE_STATUSES:
                continue
            if hit["via"] == "file name" and not all(w in _basename(src.path).lower() for w in (words or [q.lower()])):
                continue  # matched a folder name, or not every word
            out.append({**hit, "path": src.path, "kind": src.kind.value, "status": src.status.value})
            if len(out) >= k:
                break
        if len(out) < 3 and len(q) >= 3:  # typos: "hackthon" -> hackathon-demo.mp4
            out += self._similar_names(q, {h["source_id"] for h in out}, k - len(out))
        return out

    def _similar_names(self, q: str, skip: set[str], k: int) -> list[dict[str, Any]]:
        import difflib

        live = [d for d in self.kdb["sources"].find({"status": {"$nin": repo.HIDDEN_SOURCE_STATUSES}},
                                                      {"path": 1, "kind": 1, "status": 1}).limit(20000)
                if d["_id"] not in skip]
        stems = {}
        for d in live:
            stem = re.sub(r"\.[^.]+$", "", _basename(d["path"])).lower()
            for part in [stem, *re.split(r"[\s_.-]+", stem)]:
                if len(part) >= 3:
                    stems.setdefault(part, []).append(d)
        hits: dict[str, dict[str, Any]] = {}
        for word in [w for w in _TOKEN.findall(q.lower()) if len(w) >= 3] or [q.lower()]:
            for match in difflib.get_close_matches(word, list(stems), n=k, cutoff=0.75):
                for d in stems[match]:
                    hits.setdefault(d["_id"], {"source_id": d["_id"], "via": f"similar name: {match}",
                                               "path": d["path"], "kind": d.get("kind", "other"),
                                               "status": d.get("status", "")})
        return list(hits.values())[:k]

    def recent_files(self, k: int = 8) -> list[dict[str, Any]]:
        """What the search box shows before anything is typed."""
        docs = self.kdb["sources"].find({"status": {"$nin": repo.HIDDEN_SOURCE_STATUSES}}).sort("updated_at", -1).limit(k)
        return [{"source_id": d["_id"], "via": "recent", "path": d["path"], "kind": d.get("kind", "other"),
                 "status": d.get("status", "")} for d in docs]
