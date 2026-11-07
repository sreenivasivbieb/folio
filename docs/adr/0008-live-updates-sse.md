# 0008 — Server-sent events for live updates

**Context.** FR-6: an edit in one view shows in all views immediately; job progress must be
visible. The proposal specified request/response HTTP only.

**Decision.** `GET /api/events/stream` (SSE). Ledger commits, job changes, source status and voice
state are published on an in-process bus. The UI invalidates matching react-query caches
(coalesced every 150 ms). EventSource cannot send headers, so the token may be passed as a query
parameter on this endpoint (still loopback-only).

**Consequences.** One mechanism for every view; no polling. Works the same in the desktop shell
and in a plain browser during development.
