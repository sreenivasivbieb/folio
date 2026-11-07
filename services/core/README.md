# folio-core

The core service: everything that touches files, models or the database. The desktop shell starts
it as a sidecar on `127.0.0.1:<random port>` with a per-session token; the UI talks to it over a
typed HTTP API (+ SSE for live updates).

```bash
uv sync                      # Python 3.12 venv with dependencies
uv run pytest                # tests
uv run ruff check src tests  # lint
FOLIO_TOKEN=dev uv run folio-core serve --port 8765   # run standalone
uv run folio-core openapi    # print the API spec
uv run folio-core eval ../../eval/golden --min-precision 0.8
```

Start reading at [`src/folio_core/container.py`](src/folio_core/container.py): it builds every
service and shows how they depend on each other. Package-by-package overview:
[`src/folio_core/__init__.py`](src/folio_core/__init__.py). Optional extras: `speech`
(faster-whisper + microphone), `embeddings` (fastembed/ONNX).

### Adding a file type

Implement the `Parser` protocol (`ingestion/base.py`): a `name`, the `extensions` it handles, and
`parse(path, ctx) -> list[ParsedUnit]` where every unit carries a locator. Register it in
`ingestion/parsers/__init__.py`, or ship it in another package under the `folio.parsers`
entry-point group — no core changes needed.

### Adding a model provider

Implement the protocol in `providers/{llm,embeddings,stt}/base.py` and select it in
`providers/registry.py`. Set `is_local = False` for anything that sends data off the machine; the
privacy gate then requires the project's cloud opt-in.
