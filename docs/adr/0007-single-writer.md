# 0007 — One writer process; sandboxed parsers only return data

**Context.** The proposal combines an SQLite store, a job queue and parsing in separate
subprocesses (security). Several processes writing to one SQLite file leads to `SQLITE_BUSY`
contention and harder crash reasoning.

**Decision.** Only the core process writes. All writes go through `Database.write()` (process
lock + `BEGIN IMMEDIATE`). Parser subprocesses receive a path, lower their own memory limit, and
print units as JSON; the parent stores them. Reads use per-thread connections in WAL mode.

**Consequences.** No lock contention, simple crash semantics (verified by a forced-kill test).
Write throughput is bounded by one writer, which is far above what a single user generates.
