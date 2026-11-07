# @folio/ui

React + TypeScript + Vite. Runs inside the Tauri shell, or in a browser against a core started with
`npm run dev:core` (see `.env.development`).

* `src/api/` — connection (Tauri or env), the generated typed client, react-query hooks, and the
  SSE subscription that keeps every view in sync.
* `src/views/` — the four projections of the claim table: graph (Sigma.js/WebGL), swimlane
  (d3 scales, drag to edit), timeline, table (TanStack Table, inline edit, bulk actions).
* `src/features/` — one folder per product feature (sources, entities, claims, review, voice,
  evidence, jobs, history, schema, search, export).
* `src/state/` — UI state: selection (also the target of voice labels), active view, modals.

Shortcuts: `Ctrl+K` search · `Ctrl+Z` / `Ctrl+Shift+Z` undo/redo · `1–4` switch views ·
hold `Ctrl+Space` to talk · in Review: `J`/`K` move, `V` verify, `R` reject.
