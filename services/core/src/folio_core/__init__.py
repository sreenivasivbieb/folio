"""Folio core service.

Package map (each sub-package owns one responsibility from the architecture proposal):

    domain/      pure types and rules (claims, entities, fingerprints) — no I/O
    store/       SQLite: knowledge.db (durable) + index.db (disposable), migrations, repositories
    ledger/      append-only event log; every durable mutation goes through it; undo
    providers/   swappable model adapters: LLM, embeddings, speech-to-text
    ingestion/   file parsers (plugin registry), chunking, sandboxing, folder watching
    extraction/  schema-guided entity/claim extraction + entity resolution
    speech/      microphone capture and voice-label parsing
    learning/    correction store: aliases, rejections, few-shot examples, vocabulary
    query/       hybrid search, graph expansion, entity cards, view projections
    jobs/        SQLite-backed resumable job queue and worker pool
    export/      JSON / Markdown / CSV / GraphML export and import
    realtime/    in-process pub/sub that feeds the UI's SSE stream
    api/         FastAPI routers (thin: validate, call a service, return DTOs)
"""

__version__ = "0.2.0"
