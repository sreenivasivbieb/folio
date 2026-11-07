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
┌───────▼────────────────────┐  ┌─────▼──────────────────┐  ┌─────▼──────────────┐
│ knowledge.db  (durable)    │  │ providers/: rules or    │  │ your files         │
│ index.db      (disposable) │  │ LLM · embeddings · STT  │  │ never copied/moved │
└────────────────────────────┘  │ cloud = opt-in only     │  └────────────────────┘
                                └─────────────────────────┘
```

## Proposal component → code

| Proposal component | Code |
|---|---|
| Desktop shell (Tauri, Rust) | `apps/desktop/src-tauri/src/lib.rs`, `sidecar.rs` |
| UI (React, TS) | `apps/ui/src/` — views in `views/`, features in `features/` |
| Core service (Python, FastAPI) | `services/core/src/folio_core/` — wiring in `container.py`, HTTP in `api/` |
| Ingestion workers | `ingestion/` — `parsers/*` (pdf, image, docx, text/md, vtt/srt, audio/video), `sandbox.py`, `chunker.py`, `service.py`, `watcher.py` |
| Speech to text | `providers/stt/` (faster-whisper + VAD), `speech/recorder.py`, `ingestion/parsers/media.py` |
| Extraction | `extraction/` — `rules.py`, `llm.py`, `validate.py`, `resolver.py`, `service.py` |
| Store | `store/db.py`, `store/migrations/{knowledge,index}/`, `store/repo.py`, `store/vectors.py` |
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
| FR-4 schema-guided extraction | `domain/schema.py`, `schema_packs/default.yaml`, `extraction/validate.py` | `test_extraction.py::test_validation…` |
| FR-5 entity card w/ source pointers | `query/card.py`, UI `features/entities/`, `features/evidence/` | `test_query_export.py::test_hybrid_search_and_entity_card` |
| FR-6 four views, one model | `query/views.py`, UI `views/*`, SSE `api/routes/ledger.py` + `ui/src/api/events.ts` | `test_query_export.py::test_views_share_one_model` |
| FR-7 edit/merge/split/retype/reject, undo | `knowledge/service.py`, `ledger/` | `test_knowledge.py`, `test_ledger.py` |
| FR-8 learn from corrections | fingerprints in `domain/rules.py`, `knowledge.add_claim_tx`, `learning/store.py` | `test_extraction.py::test_rejected_claim_is_never_reproposed…` |
| FR-9 export/import round trip | `export/exporters.py` | `test_query_export.py::test_json_round_trip…`, `…graphml…` |
| FR-10 provenance & audit | `claims.extractor` (model + prompt version), ledger history | `test_ledger.py`, `/api/claims/{id}/history` |
| NFR privacy: zero outbound | default providers are local; `providers/privacy.py` | `test_api_privacy.py::test_zero_outbound_network…` |
| NFR reliability: forced kill | WAL + single atomic ledger groups, `jobs.recover()` | `test_reliability.py` |
| NFR cost: zero calls on unchanged data | content hash + model cache | `test_extraction.py::test_rerun_on_unchanged_data…` |
| NFR extensibility | parser entry points `folio.parsers`, provider protocols, schema packs | — |
| NFR trust: precision gate | `evaluation.py`, `eval/golden/` | `test_query_export.py::test_golden_set_meets_precision_gate` |

## Data model

Exactly the proposal's objects, split across two files (ADR-0002):

* **knowledge.db** — `settings`, `schema_versions`, `roots`, `sources`, `entities`, `aliases`,
  `claims`, `evidence`, `labels`, `event_groups`, `events` (append-only via triggers).
* **index.db** — `chunks` (+ `chunks_fts` FTS5), `chunk_vec` (sqlite-vec) or `chunk_vectors`
  (numpy fallback), `model_cache`, `jobs`, `extraction_issues`, `merge_suggestions`.

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
* Prompt injection: file text is data; the model has no tools; only schema-valid claims whose
  quote is a literal span of the chunk are accepted.
* Cloud providers are blocked unless `cloud.enabled` is set for the project (badge in the top bar).

## Known gaps / next steps

* **Packaging** (Phase 0 spike): `scripts/build-sidecar.sh` + `.github/workflows/release.yml`
  produce the PyInstaller sidecar and installers but have not been validated on all three OSes.
* **Image understanding** is OCR only; captions/CLIP embeddings plug in behind the provider
  interface. Video keyframes are not extracted yet (the audio track is transcribed).
* **Label parsing** is an English rule grammar. Mixed Hindi/English speech is transcribed by the
  multilingual Whisper model, but understanding free-form or mixed-language labels needs an LLM
  label parser producing the same plan format.
* **The default extractor is rule-based** (ADR-0005). Real extraction quality needs a local LLM
  (`FOLIO_EXTRACTOR=llm FOLIO_LLM=openai`) and a golden set built from real files.
* `POST /api/index/rebuild` deletes `index.db` in place; on Windows this can fail while other
  threads hold the file open. Safer fallback: quit the app and delete `index.db` manually.
* Phase 2+ (active learning, contradiction detection beyond single-valued attributes, dataset
  export, file moves, encrypted store, sync) are out of v1 scope by design.
