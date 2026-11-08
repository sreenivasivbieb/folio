# 0009 — Knowledge in MongoDB (Docker), open schema

**Status.** Accepted (product owner's decision, 2026-11-08). Supersedes the storage part of
[0002](0002-two-sqlite-files.md); the "derived data is disposable" split stays.

**Context.** Real files (lecture notes, research PDFs) do not fit a fixed business schema
(Contract, Meeting, …). The product owner asked for no fixed categories — data stored as flexible
JSON — and chose MongoDB, run in Docker so any developer or user gets the same database with one
command. The trade-off was raised before deciding: MongoDB is a separate server process, so the
"one installer, no server" goal of the proposal no longer holds; Docker is now a prerequisite.

**Decision.**

* **Knowledge** (entities, claims with embedded evidence, labels, sources, settings, type hints,
  the event ledger) lives in MongoDB, `docker-compose.yml` at the repo root, bound to 127.0.0.1.
  It runs as a single-node **replica set** because every ledger group is a multi-document
  transaction (undo/history depend on that atomicity).
* **Index** (chunks, FTS5, vectors, model cache, jobs) stays in SQLite `index.db`: MongoDB
  Community has no in-process vector search, and this data is disposable anyway.
* **Open schema**: an entity's `type` and a claim's `predicate` are free strings; `value` is any
  JSON. The YAML "schema" became *type hints*: colours, spoken phrases, date parsing, LLM
  suggestions. Unknown types are always accepted (`canonical_type` only reuses an existing
  spelling: "person" → "Person"). Trust rules (evidence required, quote must be a real span,
  fingerprints block re-proposing rejected facts) are unchanged.
* Aliases are embedded in the entity document; evidence is embedded in the claim document.
* Append-only ledger is enforced by the code path (no update/delete of `events`), not triggers.

**Consequences.** Flexible data, simpler documents, Mongo tooling (Compass, mongodump) works.
Users need Docker; the core waits ~20 s for MongoDB at start and otherwise exits with a clear
message. Tests use a throwaway database per test against the same container.
