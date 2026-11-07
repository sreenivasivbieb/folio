# 0001 — One monorepo: apps / services / packages

**Context.** The product has three runtimes (Rust shell, TypeScript UI, Python core) that must
version together: the UI's client is generated from the core's API.

**Decision.** A single repository:

* `apps/` — things users run: `desktop` (Tauri shell) and `ui` (React).
* `services/` — long-running processes: `core` (Python sidecar).
* `packages/` — code shared between apps: `api-client` (generated from OpenAPI).
* `docs/`, `eval/`, `scripts/` at the root.

The UI lives in its own app (not inside `desktop/`) so it can be developed in a plain browser
against a running core, without compiling Rust.

**Consequences.** One PR changes API + client + UI atomically; CI checks the generated client is
up to date. npm workspaces for JS, uv for Python, cargo for Rust — each tool stays idiomatic.
