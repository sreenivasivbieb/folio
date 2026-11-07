# 0004 — Event ledger = row snapshots next to state tables

**Context.** The proposal requires an append-only event log that drives undo, audit, learning and
later sync. Full event sourcing (state derived only by replaying events) would make every read
path depend on projections and complicate a v1.

**Decision.** State lives in normal tables. Every durable write goes through `Ledger.group()`,
which records, in the same transaction, one *event group* per user-visible action and one *event*
per touched row with its before/after snapshot. Triggers make `events`/`event_groups`
append-only. Undo/redo revert a group by restoring snapshots — itself recorded as a new group —
and refuse if a later change touched the same rows.

**Consequences.** Simple reads, exact history for any claim or entity (FR-10), undo of compound
actions (a merge touches dozens of rows) in one step, and a replication unit for future sync.
Storage grows with edits; fine for a single-user knowledge base.
