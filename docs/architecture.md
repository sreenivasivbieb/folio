# Current Folio architecture

Folio is a single-user local application: a React interface, a Tauri desktop shell and
one supervised Python process bound to loopback. It runs independently of its source
checkout. No developer-owned server, database or account handles user storage.

## Local storage

`store/local.py` stores JSON-shaped knowledge records inside a private local
`knowledge.sqlite3` file. Its narrow document interface serves domain services without
MongoDB. SQLite transactions commit changes, ledger events and sequence counters together;
uniqueness constraints protect file paths and event sequences. Lookups for source paths,
root membership and status have local indexes. A core process lock prevents two app
instances from writing the same data folder.

`store/index_db.py` holds the disposable local `index.db`: parsed chunks, FTS5 search,
vectors, jobs, extraction issues and model cache. SQLite-vec is used when available and
NumPy otherwise. Originals and durable knowledge are independent of this index.

API keys and optional Google OAuth tokens stay in the user's `secrets.json` (0600),
separate from knowledge exports. The app data folder is private (0700) on Linux. Rotating
runtime/startup logs are in its `logs` subfolder.

## Drops and processing

Folio only imports what the user drops or picks (`POST /drops`); it never scans the
computer. Dropped folders are walked with a fixed smart-ignore list (hidden entries,
VCS/dependency/cache/build folders, lockfiles, binaries, disk images); the skipped count
is reported. Files are moved or copied into the private `vault/` folder, which is the
only root Folio indexes. Duplicate content already in the vault is reused.

Supported files are hashed, parsed in a limited subprocess when appropriate, chunked
and embedded for search. The label (`POST /drops/{id}/label`, typed or transcribed) is
the primary input of the drop organizer (`organize/drops.py`): a model — or offline
rules — returns a project, summary, virtual folders, tags, entities and links, written
to the graph as Project → Folder → File plus project → tag/person/organisation. A
per-file organizer adds a readable title and description. Deep per-passage fact
extraction is opt-in (`Settings.auto_extract`, or Re-run extraction). A duplicate change
received while a job runs schedules another pass rather than losing the update.

Forget/remove and short index commits share the local knowledge writer guard. A parser
or model can finish outside that guard, but its result is discarded if the source was
forgotten, removed or changed. Failed extraction chunks retain prior proposals; only
successfully processed chunks participate in stale-result pruning.

## Knowledge and views

KnowledgeService owns entity and claim edits. Ledger groups record row snapshots and
provide undo/redo and provenance. The UI has three views — Drop & Label, Projects and
Graph — over the same claims. Organizing results are applied directly (and undoable);
results of on-demand deep extraction stay proposals in the review API. Files use server
pagination with loading/error/retry states.

The core publishes transient SSE events. The UI refreshes caches when the stream reconnects
and probes the authenticated backend with bounded requests. A desktop backend restart
re-resolves its new port; failed startup shows retry controls and the actual log location.

JSON and GraphML imports validate records first and write inside one local transaction.
A failed or conflicting import leaves the existing project intact. Native exports write
to a temporary sibling and rename only after the complete data is synced.

## Optional user-owned connections

Local rules, hashing embeddings and local AI need no hosted inference account. A user may
choose a hosted OpenAI-compatible model with their own key; file text is then processed
by that provider, while Folio's working state remains local. Loopback AI ignores HTTP proxy
environment variables so a nominally local connection does not use an outbound proxy.

Google Drive backup is optional and uses that user's own Desktop OAuth client and account.
OAuth opens the system browser, uses PKCE/state and returns to the local core. Tokens stay
in the local credentials file. The app requests drive.file access only for its own backups.
No original files or API keys enter a knowledge backup, and upload requires an explicit
Back up now action. Restore validates and imports into an empty local project.

## Packaging and validation limits

The Omarchy builder embeds production UI assets, builds a Python sidecar, and creates an
Arch x86_64 package and portable archive with checksums. Installed builds use the adjacent
sidecar and never fall back to the developer checkout. Runtime libraries are declared in
the package. No Docker, MongoDB or Python development environment is required by the app.

Tests cover local persistence, rollback, crash recovery, extraction failure, forget races,
smart-ignore filtering, drops and labels, AI and rule-based organizing, disk organization
with undo, pagination, credentials and connection health.
Provider fixtures are not live AI quality evidence. Google Drive's live OAuth and account
permissions must still be checked with the user's own credentials. Native drag-and-drop
and native Wayland behavior require testing on real target installations.

Older ADRs describe previous storage designs; ADR-0011 supersedes the MongoDB requirement.
