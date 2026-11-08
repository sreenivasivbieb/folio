# Folio

**Local-first voice labeling & knowledge organization.** Point Folio at the files already on your
machine (PDFs, scans, images, Word/Markdown/text, audio, video, VTT/SRT transcripts), *say* what
they are, and get an editable, entity-centric knowledge base where every fact links back to the
exact page, region or second it came from.

> Select files → speak labels → the system extracts entities and relations → you review and
> correct them → corrections improve the next run.

Originals are never modified, moved or copied. There are no fixed categories: people, topics,
courses, contracts — whatever the AI or you name. Facts are extracted by an LLM you choose (bring
your own key: OpenAI, OpenRouter, Qwen, Groq, any OpenAI-compatible router, or a local Ollama);
nothing leaves your machine unless you pick a hosted model, and the top bar always shows which.

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
│       │   ├── store/        MongoDB knowledge store + SQLite index.db (disposable), migrations
│       │   ├── ledger/       append-only event log → undo/redo, audit, provenance
│       │   ├── knowledge/    every write to entities/claims (validation, merge, split, edit)
│       │   ├── ingestion/    parser plugins, sandbox, chunker, hashing, folder watcher
│       │   ├── extraction/   rules + LLM extractors, validation, entity resolution
│       │   ├── speech/       mic capture, voice-label parser, label preview/confirm
│       │   ├── learning/     correction store: aliases, negatives, few-shot, vocabulary
│       │   ├── query/        hybrid search, entity cards, view projections, review queue
│       │   ├── jobs/         SQLite-backed resumable job queue + worker pool
│       │   ├── export/       JSON / GraphML (lossless) · Markdown / CSV
│       │   ├── providers/    LLM router (BYOK) · embeddings · speech-to-text · secrets · privacy
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

Prerequisites: [Docker](https://docs.docker.com/get-docker/) (for MongoDB),
[uv](https://docs.astral.sh/uv/), Node 20.19+, and for the desktop shell a Rust toolchain plus
the [Tauri system dependencies](https://tauri.app/start/prerequisites/).
Optional: `ffmpeg` (audio/video) and `tesseract` (OCR for scans and images).

```bash
docker compose up -d                         # MongoDB (single-node replica set, localhost only)
npm install                                  # JS workspaces (ui, api-client, desktop CLI)
(cd services/core && uv sync)                # Python core (pins Python 3.12)

# Option A — the desktop app (starts the core sidecar for you)
npm run dev:desktop

# Option B — browser only
npm run dev:core                             # core on 127.0.0.1:8765, token "dev"
npm run dev:ui                               # http://127.0.0.1:1420
```

Then open **Settings → AI model**, pick a provider, paste your API key, load the model list and
save. Without a model, Folio still indexes and searches everything, but finds very few facts.

Voice needs the optional speech extra; the Whisper model is downloaded only when you click
**Settings → Voice → Download** (then it works offline):

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
| `FOLIO_DATA_DIR` | OS app-data dir | `index.db`, label audio, speech models, `secrets.json` (API keys, mode 0600) |
| `FOLIO_MONGO_URI` | `mongodb://127.0.0.1:27017/?replicaSet=rs0&directConnection=true` | knowledge store |
| `FOLIO_MONGO_DB` | `folio` | database name (one per project) |
| `FOLIO_EMBEDDER` | `hashing` | `hashing` (zero download) or `fastembed` (ONNX, `--extra embeddings`) |
| `FOLIO_STT` / `FOLIO_STT_MODEL` | `auto` / `small` | speech-to-text (`none` disables) |

The LLM is not an environment variable: it is chosen per project in Settings (stored in MongoDB,
key in `secrets.json`). A hosted (non-loopback) endpoint counts as *cloud*: choosing it is the project's opt-in, and the
top bar shows it at all times.

## Status

This is the **Phase 1 (v1 core loop)** implementation of the architecture proposal: select →
index → label by voice → extract → review → correct → export, with all four views. See
[`docs/architecture.md`](docs/architecture.md) for what is implemented where, and the ADRs for
decisions that refine the proposal. Known gaps are listed at the end of the architecture doc.
