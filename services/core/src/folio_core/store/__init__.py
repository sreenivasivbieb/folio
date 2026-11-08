"""Persistence.

* ``mongo.py``    — the knowledge store (MongoDB): entities, claims, labels, sources, the ledger.
* ``index_db.py`` — the disposable index (SQLite): chunks, FTS5, vectors, model cache, jobs.
* ``repo.py``     — read queries and document <-> domain-model conversion.
* ``vectors.py``  — the vector index over chunk embeddings.
"""

from .index_db import IndexDB, utcnow
from .mongo import KnowledgeDB

__all__ = ["IndexDB", "KnowledgeDB", "utcnow"]
