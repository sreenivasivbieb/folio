"""Writes to the knowledge graph (entities, aliases, claims, evidence, schema).

Every caller — the UI's inline edits, voice labels, extraction, import — goes through
:class:`KnowledgeService`, so the data rules live in exactly one place:

* claims are validated against the active schema,
* model claims must carry evidence,
* verified/rejected claims are never overwritten by re-extraction (fingerprints),
* merges/splits/edits are ledger groups and therefore undoable.
"""

from .service import KnowledgeService

__all__ = ["KnowledgeService"]
