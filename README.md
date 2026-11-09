# Folio

Local-first file scanning, voice labeling and knowledge organization for your own computer.
Scan Home, mounted drives or any readable folder, review extracted facts, and follow every
fact back to its original file. Originals stay where they are and are never modified.

**Each user's files and working data remain on their own device.** Folio has no hosted
storage, user account service or central database. Knowledge and the search index live in
private local SQLite files. AI can be local or a hosted provider chosen with the user's
own API key. Optional Google Drive backup uses that user's own Desktop OAuth credentials;
it uploads a knowledge backup only when the user chooses **Back up now**.

## Install on Omarchy

See [installation and storage](docs/INSTALL.md). Build a native Arch package and portable
archive with `bash scripts/build-omarchy.sh`; outputs and SHA256 checksums are in
`artifacts/`. The installed app includes the frontend and Python service and runs from
any folder. It does not need Node, uv, Rust, Docker, MongoDB or this checkout on the target
machine. The Arch package declares its GTK/WebKit and audio runtime dependencies.

Open Folio from `Super+Space`, choose **Scan my computer**, and select locations. Supported
formats get content indexing; every other regular readable file gets a metadata entry.
Hidden folders, exclusion patterns and watching are configurable. Scans stream files in
background jobs and report unreadable paths without aborting the rest. Symlinks, virtual
system paths and Folio's own storage are skipped. No personal-file scan runs on install.

## Development

Prerequisites: Node 20.19+, uv (Python 3.12), and for the desktop shell Rust plus the
[Tauri Linux prerequisites](https://tauri.app/start/prerequisites/).

```bash
npm install
uv sync --project services/core
npm run dev
```

Open http://127.0.0.1:1420. This starts the local backend and UI together; Ctrl+C stops
both. Separate commands are still available as `npm run dev:core` and `npm run dev:ui`.
For the desktop shell use `npm run dev:desktop` instead. No database server is required.

## Storage and connections

* `~/.local/share/folio/knowledge.sqlite3`: your entities, claims, sources and undo history.
* `~/.local/share/folio/index.db`: rebuildable chunks, search vectors, jobs and model cache.
* `~/.local/share/folio/logs/core.log`: rotating startup and runtime logs.
* `~/.local/share/folio/secrets.json`: your API keys and optional Google OAuth credentials,
  readable only by you. Credentials are excluded from knowledge exports and Drive backups.

`FOLIO_DATA_DIR` selects a different local storage folder. Each OS user gets their own
storage. Removing the application does not delete user files, app data or backups.

In **Settings → AI model**, choose Ollama/local OpenAI-compatible inference or a hosted
provider using your own key. A hosted AI connection processes selected file text remotely;
it does not change where Folio stores its working data. Local AI is the default. Speech
models download only after an explicit action in **Settings → Voice**:

```bash
uv sync --project services/core --extra speech
```

In **Settings → Google Drive**, import your own Google Desktop OAuth credentials JSON and
sign in using the system browser. Follow [Google's Desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app)
and enable the Drive API in that Google Cloud project. Folio requests only `drive.file`
access for its own backups. Backup/restore is explicit, uses no Folio relay, and keeps
original files and credentials local. Use the same OAuth app to access its backups on
another device. A restore needs an empty local project. Live OAuth still needs validation
with the user's own credentials; automated tests use Google's API shapes with test doubles.

## Checks

```bash
npm run test:core
npm run lint:core
npm run typecheck
npm test -w @folio/ui
npm run build:ui
npm run eval
```

Tests create temporary local storage and do not require Docker or a remote database.
`npm run gen:client` regenerates the API client after endpoint changes. The rule-based
extraction quality gate uses small fixtures and is not a measure of live model quality.

## Structure

* `apps/ui`: React + TypeScript interface, graph/swimlane/timeline/table views, file inventory.
* `apps/desktop`: Tauri 2 shell, native dialogs, atomic exports and Python sidecar supervision.
* `services/core`: local file ingestion, SQLite persistence, ledger, AI routing and optional Drive.
* `packages/api-client`: generated OpenAPI types and typed HTTP client.
* `pkgbuild` and `scripts/build-omarchy.sh`: reproducible local Omarchy/Arch packaging.
* `docs/architecture.md`: current data flow and implementation limits.

The Omarchy package is the supported build target for this change. Other platform release
workflows remain in the repository but have not been validated by the Omarchy build.
