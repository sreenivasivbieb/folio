# Architecture decision records

Short records of decisions that shape the code, especially where the implementation refines the
architecture proposal. Format: context → decision → consequences. Status is *Accepted* unless noted.

| # | Decision |
|---|---|
| [0001](0001-monorepo-layout.md) | One monorepo: apps / services / packages |
| [0002](0002-two-sqlite-files.md) | Split storage: durable `knowledge.db` + disposable `index.db` |
| [0003](0003-voice-and-watching-in-core.md) | Microphone capture and folder watching live in the core, not the shell |
| [0004](0004-ledger-row-snapshots.md) | Event ledger = row snapshots next to state tables (not full event sourcing) |
| [0005](0005-offline-default-providers.md) | Offline defaults: rule extractor, hashing embedder, fake LLM |
| [0006](0006-pdf-library.md) | pypdfium2 instead of PyMuPDF (licence) |
| [0007](0007-single-writer.md) | One writer process; sandboxed parsers only return data |
| [0008](0008-live-updates-sse.md) | Server-sent events for live updates across views |
