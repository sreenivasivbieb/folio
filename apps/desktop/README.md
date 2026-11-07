# @folio/desktop

The Tauri 2 shell. Intentionally thin (see `src-tauri/src/lib.rs`):

* window + native open/save dialogs,
* `sidecar.rs`: launches the core with a fresh token, waits for `FOLIO_READY {"port": N}`,
  restarts it if it crashes, kills it on exit; the UI asks for the connection via
  `core_connection`,
* best-effort global push-to-talk (Ctrl+Alt+Space), emitted to the UI as `folio://push-to-talk`.

Core launch order: `FOLIO_CORE_CMD` env override → bundled `folio-core` binary next to the app
(release) → `services/core/.venv/bin/folio-core` → `uv run` (debug).

```bash
npm run dev           # from this folder, or `npm run dev:desktop` at the root
cd src-tauri && cargo test -- --ignored   # integration test: real core, token, shutdown
```

Release bundles (Phase 0 spike): `scripts/build-sidecar.sh`, then
`npx tauri build --config src-tauri/tauri.release.conf.json`.
