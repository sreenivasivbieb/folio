"""Vector index over chunk embeddings.

Uses the sqlite-vec ``vec0`` virtual table when the extension loads; otherwise falls back to
brute-force cosine similarity in numpy over the ``chunk_vectors`` table. Both are keyed by the
chunk's SQLite rowid so they join cheaply with ``chunks``.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from .index_db import IndexDB


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


class VectorIndex:
    def __init__(self, db: IndexDB, dim: int, model_id: str) -> None:
        self.db = db
        self.dim = dim
        self.model_id = model_id
        self.ensure()

    def ensure(self) -> None:
        with self.db.write() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='embed_model'").fetchone()
            if row and row[0] != f"{self.model_id}:{self.dim}":
                # Embedding model changed: old vectors are meaningless. Drop them.
                conn.execute("DELETE FROM chunk_vectors")
                conn.execute("DROP TABLE IF EXISTS chunk_vec")
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('embed_model', ?)",
                (f"{self.model_id}:{self.dim}",),
            )
            if self.db.has_vec:
                conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0("
                    f"embedding float[{self.dim}] distance_metric=cosine)"
                )

    def add(self, conn: sqlite3.Connection, chunk_rowid: int, vec: np.ndarray) -> None:
        if self.db.has_vec:
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                (chunk_rowid, to_blob(vec)),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vectors(chunk_rowid, vec) VALUES (?, ?)",
                (chunk_rowid, to_blob(vec)),
            )

    def remove(self, conn: sqlite3.Connection, chunk_rowids: list[int]) -> None:
        if not chunk_rowids:
            return
        table, col = ("chunk_vec", "rowid") if self.db.has_vec else ("chunk_vectors", "chunk_rowid")
        # Delete in batches: vec0 virtual tables do not support "IN (subquery)" everywhere, and one
        # "?" per row would exceed SQLite's host-parameter limit for large documents.
        for i in range(0, len(chunk_rowids), 500):
            batch = chunk_rowids[i:i + 500]
            conn.execute(f"DELETE FROM {table} WHERE {col} IN ({','.join('?' * len(batch))})", batch)

    def search(self, query: np.ndarray, k: int) -> list[tuple[int, float]]:
        """Return [(chunk_rowid, similarity)] best first."""
        if not np.any(query):  # e.g. a query of only punctuation: nothing to compare with
            return []
        conn = self.db.reader()
        if self.db.has_vec:
            rows = conn.execute(
                "SELECT rowid, distance FROM chunk_vec WHERE embedding MATCH ? AND k = ?",
                (to_blob(query), k),
            ).fetchall()
            return [(r[0], 1.0 - float(r[1])) for r in rows if r[1] is not None]
        rows = conn.execute("SELECT chunk_rowid, vec FROM chunk_vectors").fetchall()
        if not rows:
            return []
        ids = np.array([r[0] for r in rows])
        mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), -1)
        q = query / (np.linalg.norm(query) or 1.0)
        sims = mat @ q / (np.linalg.norm(mat, axis=1) + 1e-9)
        top = np.argsort(-sims)[:k]
        return [(int(ids[i]), float(sims[i])) for i in top]
