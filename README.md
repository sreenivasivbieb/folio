# Folio

**Local-first voice labeling & knowledge organization.** Point Folio at the files already on your
machine (PDFs, scans, images, Word/Markdown/text, audio, video, VTT/SRT transcripts), *say* what
they are, and get an editable, entity-centric knowledge base where every fact links back to the
exact page, region or second it came from.

> Select files → speak labels → the system extracts entities and relations → you review and
> correct them → corrections improve the next run.

Originals are never modified, moved or copied. Everything runs on your machine; cloud models are
opt-in per project, with a visible indicator.

---

## Repository layout

```
folio/
├── apps/
│   ├── desktop/          Tauri 2 shell (Rust): window, dialogs, hotkey, sidecar supervision
│   │   └── src-tauri/src/{lib.rs, sidecar.rs}
│   └── ui/               React + TypeScript + Vite
│       └── src/
│           ├── api/        typed client wiring, react-query hooks, SSE live updates
│           ├── state/      selection / view state (tiny external store), toasts
│           ├── app/        layout, top bar, keyboard shortcuts
│           ├── views/      graph · swimlane · timeline · table  (one data model, four projections)
│           ├── features/   sources, entities, claims, review, voice, evidence, jobs, history,
│           │               schema, search, export
│           ├── components/ shared primitives (modal, badges)
│           └── lib/        formatting, schema helpers
├── services/
│   └── core/             Python 3.12 + FastAPI "core service" (runs as the app's sidecar)
│       ├── src/folio_core/
│       │   ├── domain/       pure types & rules: claims, entities, fingerprints, schema, values
│       │   ├── store/        SQLite: knowledge.db (durable) + index.db (disposable), migrations
│       │   ├── ledger/       append-only event log → undo/redo, audit, provenance
│       │   ├── knowledge/    every write to entities/claims (validation, merge, split, edit)
│       │   ├── ingestion/    parser plugins, sandbox, chunker, hashing, folder watcher
│       │   ├── extraction/   rules + LLM extractors, validation, entity resolution
│       │   ├── speech/       mic capture, voice-label parser, label preview/confirm
│       │   ├── learning/     correction store: aliases, negatives, few-shot, vocabulary
│       │   ├── query/        hybrid search, entity cards, view projections, review queue
│       │   ├── jobs/         SQLite-backed resumable job queue + worker pool
│       │   ├── export/       JSON / GraphML (lossless) · Markdown / CSV
│       │   ├── providers/    LLM · embeddings · speech-to-text adapters + privacy gate
│       │   ├── realtime/     pub/sub feeding the SSE stream
│       │   ├── api/          FastAPI routers (thin), DTOs, token/origin security
│       │   ├── container.py  composition root — read this to see how it all fits
│       │   └── main.py       CLI: serve · openapi · voice · eval
│       └── tests/          pytest: ledger, ingestion, extraction, labels, query/export,
│                           API security, zero-network privacy, forced-kill reliability
├── packages/
│   └── api-client/       TypeScript client GENERATED from the core's OpenAPI spec
├── eval/golden/          labeled extraction cases (release gate)
├── docs/
│   ├── architecture.md   proposal → code map, data flow, data model
│   └── adr/              architecture decision records (incl. deviations from the proposal)
└── scripts/              packaging helpers (sidecar binary)
```

Dependency direction in the core is strictly inward: `api → services (knowledge, ingestion,
extraction, speech, query) → ledger/store → domain`. `domain/` imports nothing from the rest.

## Quick start (development)

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 20.19+, and for the desktop shell a Rust
toolchain plus the [Tauri system dependencies](https://tauri.app/start/prerequisites/).
Optional: `ffmpeg` (audio/video) and `tesseract` (OCR for scans and images).

```bash
npm install                                  # JS workspaces (ui, api-client, desktop CLI)
(cd services/core && uv sync)                # Python core (pins Python 3.12)

# Option A — the desktop app (starts the core sidecar for you)
npm run dev:desktop

# Option B — browser only
npm run dev:core                             # core on 127.0.0.1:8765, token "dev"
npm run dev:ui                               # http://127.0.0.1:1420
```

Voice needs the optional speech extra (downloads a Whisper model once, then works offline):

```bash
cd services/core && uv sync --extra speech   # faster-whisper + sounddevice
```

Without it, every label can be typed — it goes through exactly the same pipeline.

### Push-to-talk

* In the app: hold the mic button or **Ctrl+Space**.
* Globally: **Ctrl+Alt+Space** (Windows, macOS, X11).
* Wayland compositors (e.g. Hyprland) don't allow apps to grab global keys; bind one yourself:
  `bind = SUPER, V, exec, uv run --project ~/path/to/folio/services/core folio-core voice toggle`

### Everyday commands

| Command | What it does |
|---|---|
| `npm run test:core` | Core test suite (pytest) |
| `npm run lint:core` | Ruff |
| `npm run eval` | Extraction precision/recall on `eval/golden` (fails below 0.8) |
| `npm run gen:client` | Regenerate `packages/api-client` after changing the API |
| `npm run typecheck` | Type-check the TypeScript workspaces |
| `npm test -w @folio/ui` | UI unit tests (vitest) |

## Configuration

The core reads `FOLIO_*` environment variables (see `services/core/src/folio_core/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `FOLIO_DATA_DIR` | OS app-data dir | where `knowledge.db`, `index.db`, label audio and models live |
| `FOLIO_EXTRACTOR` | `rules` | `rules` (offline, deterministic) or `llm` |
| `FOLIO_LLM` | `fake` | `fake` or `openai` (any OpenAI-compatible endpoint: Ollama, llama.cpp, vLLM, cloud) |
| `FOLIO_LLM_BASE_URL` / `FOLIO_LLM_MODEL` | `http://127.0.0.1:11434/v1` / `qwen2.5:7b-instruct` | LLM endpoint & model |
| `FOLIO_EMBEDDER` | `hashing` | `hashing` (zero download) or `fastembed` (ONNX, `--extra embeddings`) |
| `FOLIO_STT` / `FOLIO_STT_MODEL` | `auto` / `small` | speech-to-text (`none` disables) |

A non-loopback LLM endpoint counts as *cloud* and is refused until the project opts in (top-bar
privacy badge).

## Status

This is the **Phase 1 (v1 core loop)** implementation of the architecture proposal: select →
index → label by voice → extract → review → correct → export, with all four views. See
[`docs/architecture.md`](docs/architecture.md) for what is implemented where, and the ADRs for
decisions that refine the proposal. Known gaps are listed at the end of the architecture doc.
