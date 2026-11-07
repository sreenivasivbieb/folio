"""No lock-in (FR-9): the data outlives the tool.

* JSON     — lossless: every durable table, including the full event ledger. Import restores it.
* GraphML  — the graph (entities, aliases, all claims + evidence + provenance); import restores it.
* Markdown — human-readable notes, one section per entity.
* CSV      — zip of entities.csv / claims.csv / evidence.csv for spreadsheets.
"""

from .exporters import Exporter

__all__ = ["Exporter"]
