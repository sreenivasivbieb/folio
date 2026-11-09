> Superseded by [ADR-0011](0011-local-user-owned-storage.md) for the current storage implementation.

# 0002 — Split storage: durable `knowledge.db` + disposable `index.db`

**Status.** Superseded in part by [0009](0009-mongodb-open-schema.md): durable knowledge now lives in
MongoDB; the disposable `index.db` described here is unchanged.

**Context.** The proposal's design principle is "derived data is disposable, user decisions are
not", but it put both in one SQLite file. Backups, "rebuild the index", and changing the embedding
model are then surgery on the file that also holds the irreplaceable data.

**Decision.** Two SQLite files, one logical database (index.db is `ATTACH`ed as schema `ix`):

* `knowledge.db` — entities, aliases, claims, evidence, labels, schema versions, roots/sources,
  settings and the event ledger. *Back this up.*
* `index.db` — chunks, FTS5 index, vectors, model cache, jobs, extraction issues, merge
  suggestions. *Delete it any time*; `POST /api/index/rebuild` recreates it.

Evidence stores `source_id + locator + quote` (not only a chunk id) so it survives a rebuild.

**Consequences.** Backup = copy one file. Cross-file transactions are not atomic in WAL mode, which
is acceptable because index.db can always be regenerated. Both files are still one install, no
server.
