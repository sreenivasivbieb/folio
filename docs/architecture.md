# Architecture

This maps the architecture proposal ("Local-First Voice Labeling & Knowledge Organization
Platform", Nov 2026) onto the code. Decisions that refine the proposal are recorded as ADRs in
[`docs/adr/`](adr/).

## Runtime topology

```
┌──────────────── Desktop shell · Tauri 2 (apps/desktop) ────────────────┐
│  window · file/save dialogs · global hotkey (best effort)              │
│  sidecar.rs: spawn core, per-session token, read FOLIO_READY, restart  │
│  ┌──────────── UI · React + TS (apps/ui) ────────────┐                 │
│  │ graph · swimlane · timeline · table · review ·    │                 │
│  │ evidence viewer · voice bar                       │                 │
│  └──────────────┬────────────────────────────────────┘                 │
└─────────────────┼──────────────────────────────────────────────────────┘
                  │ HTTP/JSON + SSE on 127.0.0.1:<random>, Bearer token,
                  │ typed client generated from OpenAPI (packages/api-client)
┌─────────────────▼──────── Core service · Python + FastAPI (services/core) ──┐
│ ingestion (sandboxed parsers) · speech (mic + parser) · extraction · query  │
│ jobs (SQLite queue) · learning · ledger · export · realtime (SSE)           │
└───────┬─────────────────────────────┬───────────────────────────┬───────────┘
        │ read/write (single writer)  │ run models                │ read-only
┌───────▼────────────────────────┐ ┌──▼─────────────────────┐  ┌──▼─────────────────┐
│ MongoDB (Docker, replica set)  │ │ LLM router: your key → │  │ your files         │
│   knowledge + ledger, durable  │ │ OpenAI/OpenRouter/Qwen │  │ never copied/moved │
│ index.db (SQLite), disposable  │ │ /Groq/Ollama/custom;   │  └────────────────────┘
│   chunks · FTS5 · vectors · jobs│ │ rules if none · STT    │
└────────────────────────────────┘ └────────────────────────┘
```

## Proposal component → code

| Proposal component | Code |
|---|---|
| Desktop shell (Tauri, Rust) | `apps/desktop/src-tauri/src/lib.rs`, `sidecar.rs` |
| UI (React, TS) | `apps/ui/src/` — views in `views/`, features in `features/` |
| Core service (Python, FastAPI) | `services/core/src/folio_core/` — wiring in `container.py`, HTTP in `api/` |
| Ingestion workers | `ingestion/` — `parsers/*` (pdf, image, docx, text/md, vtt/srt, audio/video), `sandbox.py`, `chunker.py`, `service.py`, `watcher.py` |
| Speech to text | `providers/stt/` (faster-whisper + VAD), `speech/recorder.py`, `ingestion/parsers/media.py` |
| Extraction | `extraction/` — `llm.py` (open-schema prompt), `rules.py` (offline fallback), `validate.py`, `resolver.py`, `service.py`; LLM routing in `providers/llm/router.py` |
| Store | `store/mongo.py` (knowledge), `store/index_db.py` + `store/migrations/index/` (index), `store/repo.py`, `store/vectors.py` |
| Query engine | `query/search.py` (FTS5 + vectors, RRF), `query/views.py` (recursive-CTE graph expansion), `query/card.py` |
| Job queue | `jobs/queue.py`, `jobs/worker.py` |
| Correction learning | `learning/store.py` |
| Event log & feedback store | `ledger/ledger.py` |

## Requirements → where they are met (and tested)

| Req | Implementation | Test |
|---|---|---|
| FR-1 select/watch, read-only, hash skip | `ingestion/service.py` (`_track`, `index_source`), `watcher.py` | `test_ingestion.py::test_unchanged_file_costs_nothing…` |
| FR-2 multimodal + locators | `ingestion/parsers/*`, `chunker.py` | `test_ingestion.py::test_every_chunk_has_a_locator` |
| FR-3 voice labels, preview, questions | `speech/label_parser.py`, `speech/labels.py`, UI `features/voice/` | `test_labels.py` |
| FR-4 extraction (open schema; hints guide, never reject) | `domain/schema.py`, `schema_packs/default.yaml`, `extraction/validate.py` | `test_extraction.py::test_validation…`, `test_knowledge.py::test_open_schema…` |
| FR-5 entity card w/ source pointers | `query/card.py`, UI `features/entities/`, `features/evidence/` | `test_query_export.py::test_hybrid_search_and_entity_card` |
| FR-6 four views, one model | `query/views.py`, UI `views/*`, SSE `api/routes/ledger.py` + `ui/src/api/events.ts` | `test_query_export.py::test_views_share_one_model` |
| FR-7 edit/merge/split/retype/reject, undo | `knowledge/service.py`, `ledger/` | `test_knowledge.py`, `test_ledger.py` |
| FR-8 learn from corrections | fingerprints in `domain/rules.py`, `knowledge.add_claim_tx`, `learning/store.py` | `test_extraction.py::test_rejected_claim_is_never_reproposed…` |
| FR-9 export/import round trip | `export/exporters.py` | `test_query_export.py::test_json_round_trip…`, `…graphml…` |
| FR-10 provenance & audit | `claims.extractor` (model + prompt version), ledger history | `test_ledger.py`, `/api/claims/{id}/history` |
| NFR privacy: zero outbound | default providers are local; `providers/privacy.py` | `test_api_privacy.py::test_zero_outbound_network…` |
| NFR reliability: forced kill | MongoDB transactions per ledger group, WAL index, `jobs.recover()` | `test_reliability.py` |
| NFR cost: zero calls on unchanged data | content hash + model cache | `test_extraction.py::test_rerun_on_unchanged_data…` |
| NFR extensibility | parser entry points `folio.parsers`, provider protocols + LLM presets, hint packs | — |
| BYOK LLM, key never stored in DB/exports | `providers/llm/router.py`, `providers/secrets.py` | `test_llm_and_sources.py` |
| NFR trust: precision gate | `evaluation.py`, `eval/golden/` | `test_query_export.py::test_golden_set_meets_precision_gate` |

## Data model

Exactly the proposal's objects, with no fixed categories (ADR-0009):

* **MongoDB** (`folio` database) — `settings`, `schema_versions` (type *hints*), `roots`,
  `sources`, `entities` (aliases embedded), `claims` (evidence embedded), `labels`,
  `event_groups`, `events` (append-only), `counters`.
* **index.db** (SQLite) — `chunks` (+ `chunks_fts` FTS5), `chunk_vec` (sqlite-vec) or
  `chunk_vectors` (numpy fallback), `model_cache`, `jobs`, `extraction_issues`,
  `merge_suggestions`.

Entity `type` and claim `predicate` are free strings; `value` is any JSON value. Hints add
colours, spoken phrases and date parsing, and are passed to the LLM as suggestions.

The unit of knowledge is the **claim**. A relation is a claim whose `object_id` is an entity, so
graph, timeline and swimlane are projections of the same rows. Built-in predicates:
`represented_by` (this entity *is* this file), `mentions` (document → entity), `mentioned`
(dated mention; feeds the timeline when no typed date attribute fits).

Evidence stores `source_id + locator + quote`, not just a chunk id, so it survives deleting and
rebuilding `index.db`.

### The trust rules, as code

1. *Every claim has evidence or is a user assertion* — `KnowledgeService.add_claim_tx` refuses a
   model claim without evidence; `extraction/validate.py` refuses a quote that is not a real span.
2. *Re-extraction only proposes* — a claim's `fingerprint` (subject, predicate, value/object) is
   checked on every write; a model can never re-add a rejected fact or alter a verified one.
3. *Merges rewrite no history* — merges are ledger groups; undo restores every row.
4. *Same claims feed every view* — `query/views.py`.

## Flows

**Indexing.** `POST /roots` → scan → `sources` rows → job `index_source`: hash unchanged → stop;
else parse in a sandboxed subprocess → chunk → embed (reusing vectors of unchanged chunks) →
replace chunks → job `extract_source`.

**Extraction.** Per chunk: model-cache lookup (hash, model, prompt version, schema version) → run
extractor → validate → resolve names to entities (exact alias, else new `auto` entity + merge
*suggestion*) → write `proposed` claims via `KnowledgeService` (blocked if rejected before) →
prune stale proposals of this source.

**Voice label.** Hold to talk → core records WAV → transcribe with the personal vocabulary as
prompt → parse into a plan (ops + questions) → preview → user answers questions → confirm →
one ledger group (`actor=voice`), audio + transcript are the evidence.

**Live updates.** Every committed ledger group is published on the in-process bus → SSE →
the UI invalidates its queries → all views re-render.

## Security

* Core binds `127.0.0.1`, random port; per-session token (constant-time compare); Origin allow-list.
* Untrusted files are parsed in a subprocess with an address-space limit and a timeout.
* Prompt injection: file text is data; the model has no tools; only well-formed claims whose
  quote is a literal span of the chunk are accepted.
* Cloud providers are blocked unless `cloud.enabled` is set for the project (badge in the top bar);
  choosing a hosted LLM in Settings is that opt-in.
* API keys live in `<data_dir>/secrets.json` (0600) — never in MongoDB, the ledger, exports or API
  responses. MongoDB is bound to 127.0.0.1 only.
* Models (speech) are downloaded only by an explicit user action, with progress.

## Known gaps / next steps

* **Packaging** (Phase 0 spike): `scripts/build-sidecar.sh` + `.github/workflows/release.yml`
  produce the PyInstaller sidecar and installers but have not been validated on all three OSes.
* **Image understanding** is OCR only; captions/CLIP embeddings plug in behind the provider
  interface. Video keyframes are not extracted yet (the audio track is transcribed).
* **Label parsing** is an English rule grammar. Mixed Hindi/English speech is transcribed by the
  multilingual Whisper model, but understanding free-form or mixed-language labels needs an LLM
  label parser producing the same plan format.
* **Without an AI model the rule extractor finds very little** in real documents (ADR-0010). Real
  quality needs a model (Settings → AI model) and a golden set built from your own files.
* **MongoDB needs Docker** (ADR-0009): the desktop installer no longer works without it. The core
  waits ~20 s for MongoDB at start and otherwise exits with a clear message.
* Real LLM extraction has been exercised end to end through the router with a local
  OpenAI-compatible test double, not yet against a hosted provider with a real key.
* Phase 2+ (active learning, contradiction detection beyond single-valued attributes, dataset
  export, file moves, encrypted store, sync) are out of v1 scope by design.
