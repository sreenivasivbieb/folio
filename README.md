# Folio

[![CI](https://github.com/sreenivasivbieb/folio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sreenivasivbieb/folio/actions/workflows/ci.yml)

**Turn files on your computer into searchable, connected knowledge.**

Folio is a desktop file organizer for **Windows and Linux** (including Omarchy/Arch). Scan folders and mounted drives,
search document passages, review extracted people and facts, and explore their
connections in graph, table, timeline and swimlane views. Every extracted fact keeps
its supporting source evidence.

Your originals stay in place. Folio stores its knowledge and search index in private
local files on your machine. Choose offline processing, a local AI model, or a cloud
AI provider with your own API key. Optional Google Drive backup uses your own Google
account and OAuth credentials.

[Install](#install) · [First scan](#your-first-scan) ·
[Storage](#your-data-and-privacy) · [AI](#choose-your-ai) ·
[Google Drive](#optional-google-drive-backup) · [Development](#development)

## What you can do

- **Scan your computer:** select Home, mounted drives, the readable filesystem, or
  custom folders. Background jobs report progress and individual file errors.
- **Search with evidence:** find indexed passages and trace them to source files,
  document pages, text lines or media timestamps.
- **Review extracted knowledge:** edit, verify or reject proposed facts, with history
  and undo/redo. Explore connections in graph, table, timeline and swimlane views.
- **Add voice labels:** hold a key and speak — in English, Hindi or Hinglish. Speech is
  recognised and translated to English on your computer by an explicitly downloaded
  Whisper model; you review (and can correct) the result before anything is saved.
- **Keep portable backups:** export JSON, GraphML, Markdown or CSV, and restore Folio
  JSON backups into an empty project.

## Install

| Platform | Installer | Built by |
| --- | --- | --- |
| Windows 10/11 x64 | `Folio_x.y.z_x64-setup.exe` (per-user) or `.msi` | [Release workflow](.github/workflows/release.yml) |
| Linux x86_64, any distro | `Folio_x.y.z_amd64.AppImage` (`chmod +x`, then run) | Release workflow |
| Debian / Ubuntu | `Folio_x.y.z_amd64.deb` (`sudo apt install ./Folio_*.deb`) | Release workflow |
| Fedora / openSUSE | `Folio-x.y.z-1.x86_64.rpm` (`sudo dnf install ./Folio-*.rpm`) | Release workflow |
| Omarchy / Arch | `folio-x.y.z-1-x86_64.pkg.tar.zst` | `scripts/build-omarchy.sh` (below) |

Every installer bundles the core service, speech recognition, audio/video decoding and
microphone support — no Python, ffmpeg or other runtime to install. Windows uses the
system WebView2 (the installer fetches it if missing). Push a tag like `v0.3.0` (or run
the workflow manually) to build all of them; tagged builds are attached to a draft
GitHub release with SHA-256 checksums.

## Install on Omarchy

The current package target is **Omarchy / Arch Linux, x86_64**, version **0.2.0**.
GitHub release assets have not been published yet. Build the installer from this
repository, or install a package produced by the build below.

### Build the installer

The build machine needs these tools and libraries:

| Requirement | Used for |
| --- | --- |
| Git, Node.js 22.12+ and npm | Source checkout and React interface |
| [uv](https://docs.astral.sh/uv/) and Python 3.12 | Python core and bundled service |
| Stable Rust and Cargo | Tauri desktop shell |
| Arch `base-devel` and `zstd` | Native compilation and package creation |
| `webkit2gtk-4.1`, `gtk3`, `openssl`, `portaudio`, `xdg-utils` | Desktop, audio and system-browser integration |

See the [Tauri Linux prerequisites](https://v2.tauri.app/start/prerequisites/) for
system dependency setup. Python 3.12 is selected by the core project's configuration.

```bash
git clone https://github.com/sreenivasivbieb/folio.git
cd folio
npm ci
uv sync --project services/core
bash scripts/build-omarchy.sh
```

The build writes these files to `artifacts/`:

| File | Purpose |
| --- | --- |
| `folio-0.2.0-1-x86_64.pkg.tar.zst` | Arch package with launcher entry and runtime dependencies |
| `folio-omarchy-x86_64.tar.zst` | Portable desktop app and bundled core service |
| `SHA256SUMS` | Checksums for both artifacts |

### Install and launch

From the `artifacts/` folder:

```bash
sha256sum --check SHA256SUMS
sudo pacman -U ./folio-0.2.0-1-x86_64.pkg.tar.zst
folio
```

You can also open **Folio** from the Omarchy launcher with `Super+Space`.
The installed package includes the interface and Python service. Development tools
and a source checkout are only needed to build it. MongoDB and Docker are not required.

For a portable run, extract the archive and keep its two executables together:

```bash
tar --zstd -xf folio-omarchy-x86_64.tar.zst
./folio-omarchy/folio
```

The portable app needs the same runtime libraries as the Arch package. See
[installation details](docs/INSTALL.md) for storage, removal and migration notes.

## Your first scan

1. Open Folio and choose **Scan my computer**.
2. Select Home, a mounted drive, the readable filesystem, or a custom path.
3. Choose hidden-file, exclusion and folder-watching settings, then start the scan.
4. Open **Activity** to follow indexing progress and inspect failed jobs.
5. Search your files and review extracted claims before marking them verified.

Scanning reads originals in place. It does not copy, move or modify them. Installation
starts no personal-file scan; selected folders are rescanned on later app launches.

Folio inventories readable regular files in your selected locations. Supported formats
get content indexing; other formats appear as **Metadata only**. Symlinks, unreadable
paths, virtual system directories and Folio's own data folder are skipped. Hidden
folders and common cache, dependency and credential directories are excluded by default.
You can adjust exclusions in the scan dialog.

### Supported content

| File family | Extensions | Processing |
| --- | --- | --- |
| Text and Markdown | `.txt`, `.md`, `.markdown` | Text extraction with line references |
| PDF | `.pdf` | Text extraction; scanned pages use optional Tesseract OCR |
| Word | `.docx` | Document text extraction |
| Subtitles | `.srt`, `.vtt` | Text with timestamps |
| Images | `.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`, `.bmp`, `.gif` | Optional OCR; basic image details when text is unavailable |
| Audio | `.mp3`, `.wav`, `.m4a`, `.ogg`, `.oga`, `.opus`, `.flac`, `.aac`, `.wma` | Local transcription with timestamps |
| Video | `.mp4`, `.mkv`, `.mov`, `.webm`, `.avi`, `.m4v`, `.wmv` | Local transcription of the audio track |

OCR requires Tesseract with English language data (optional on every platform).
Audio/video indexing needs only the speech model: download it once in
**Settings → Voice** (~480 MB). Decoding is built in — no ffmpeg needed.

## Your data and privacy

**Folio has no developer-operated storage service, shared database or required Folio
account.** Each operating-system user has their own local app data.

On Linux, the default folder is `~/.local/share/folio/`, or `$XDG_DATA_HOME/folio/`
when `XDG_DATA_HOME` is set:

| Local file or folder | Contents |
| --- | --- |
| `knowledge.sqlite3` | Sources, entities, claims, settings and undo history |
| `index.db` | Rebuildable parsed content, search index, vectors, jobs and model cache |
| `secrets.json` | Your AI API keys and optional Google OAuth credentials/tokens |
| `labels/` | Locally recorded voice-label audio |
| `logs/core.log` | Rotating startup and runtime logs |

Set `FOLIO_DATA_DIR` before launching to choose another local storage folder. The
Linux app data folder uses private permissions (`0700`); credentials use `0600`.
These are local SQLite files, with no database server to start or administer.

You control the connections that can send data elsewhere:

| Choice | Data handling |
| --- | --- |
| Default offline processing | Rule-based extraction and search run on this device |
| Local AI endpoint | Document text goes to the local model server you configure |
| Hosted AI provider | Document text is sent to your chosen provider for processing using your key |
| Google Drive **Back up now** | A knowledge backup is uploaded to your Google account |

Credentials are excluded from knowledge exports and Drive backups. Backups can contain
document excerpts, source paths and history, so choose their destination accordingly.
Removing the app retains your originals and local app data.

## Choose your AI

Folio works without an AI account using offline pattern matching. This baseline finds
simple patterns; richer extraction needs a model you connect yourself.

In **Settings → AI model**:

1. Choose **Ollama** for a model running on this computer, or a custom local
   OpenAI-compatible endpoint. Start your local model server separately.
2. Alternatively, choose a hosted preset such as OpenRouter, OpenAI, Qwen or Groq,
   or enter a custom compatible URL, and supply your own API key.
3. Use **Load models**, select an available model, and **Save**.
4. Use **Test** to check the connection, then **Extract all files now** to process
   existing files with the selected model.

Saving a hosted endpoint enables cloud processing for the project. The top bar shows
**Local AI** or **Cloud AI**. Disable cloud processing in **Settings → Privacy**.
Working knowledge remains in your local Folio files with either choice.

## Optional Google Drive backup

Drive integration backs up and restores your Folio knowledge using **your own Google
Cloud project, OAuth client and Google account**.

1. In your Google Cloud project, enable the Drive API and create an OAuth client
   with application type **Desktop app**. Follow
   [Google's Desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app).
2. Download that client's credentials JSON.
3. Open **Settings → Google Drive** and import the JSON.
4. Choose **Prepare Google sign-in**, then **Continue in system browser**, and
   authorize with your Google account.
5. Choose **Back up now** whenever you want to save a backup.

Folio uses a local callback, PKCE and Google's `drive.file` scope for its backups;
see [Google's scope documentation](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).
Uploads are manual. A backup includes knowledge, evidence quotes, local source paths,
settings and history. Original documents, recorded audio, API keys and OAuth tokens
are excluded.

Use the same OAuth client on another device to access its backups. **Restore locally**
requires an empty local project; source documents must be available separately to
reopen or rescan them. **Disconnect locally** removes this device's Drive credentials.
Google account permissions can also be revoked in your Google account.

For a local backup, use **Settings → Data** to export JSON and restore it into an empty
project. Older Folio JSON exports are supported; existing MongoDB Docker volumes are
left untouched and are not automatically migrated.

## Development

With Node.js 22.12+, npm and uv installed, run these commands from the repository root:

```bash
npm ci
uv sync --project services/core
npm run dev
```

Open **http://127.0.0.1:1420**. This starts the backend and interface together;
`Ctrl+C` stops both. Separate commands are `npm run dev:core` and `npm run dev:ui`.
Native desktop development also needs Rust and the Tauri system libraries:

```bash
npm run dev:desktop
```

For speech support in a development environment:

```bash
uv sync --project services/core --extra speech
```

Then download the speech model explicitly in **Settings → Voice**.

### Checks

```bash
npm run test:core
npm run lint:core
npm run typecheck
npm test -w @folio/ui
npm run build:ui
npm run eval
```

After changing API endpoints, regenerate the typed client with `npm run gen:client`.
Tests use temporary local storage. The extraction quality gate uses small fixtures;
it measures the rule extractor on those fixtures, rather than live AI model quality.

### Repository layout

| Path | Purpose |
| --- | --- |
| [`apps/ui`](apps/ui) | React and TypeScript interface |
| [`apps/desktop`](apps/desktop) | Tauri shell, native dialogs and core supervision |
| [`services/core`](services/core) | Python ingestion, local persistence, search, ledger and providers |
| [`packages/api-client`](packages/api-client) | Generated OpenAPI types and typed HTTP client |
| [`pkgbuild`](pkgbuild) | Arch package metadata and desktop entry |
| [`scripts/build-omarchy.sh`](scripts/build-omarchy.sh) | Omarchy package and portable archive builder |
| [`docs/architecture.md`](docs/architecture.md) | Data flow, persistence and implementation boundaries |
| [`docs/adr`](docs/adr) | Architecture decisions, including the local-storage migration |

## Troubleshooting and current limits

| Symptom | Where to look |
| --- | --- |
| Core service fails to start | Inspect `logs/core.log` in your data folder; check whether another Folio instance is using that folder |
| Some files are absent from a scan | Check location permissions, hidden-file settings, exclusions and Activity errors |
| A file says **Metadata only** | Its format has no content parser; its path and metadata are still inventoried |
| Images or scanned PDFs have no extracted text | Check Tesseract and its English language data |
| Audio/video indexing fails | Check the speech-model download (Settings → Voice) and the failed job in Activity |
| Voice: nothing happens on Wayland | Apps can't grab global keys there: bind a desktop shortcut to `folio-core voice toggle` (Settings → Voice) |
| Voice: a name is misheard | Click **Edit** in the label preview, fix the text, **Re-check** |
| AI connection fails | Check the local server or hosted provider URL, model and your API key; use **Test** |
| Drive restore is unavailable | Restore into an empty project using the OAuth client that created the backup |

The Omarchy x86_64 package has been built and checked with generated sample files,
including scanning and persistence after restart. Live Google sign-in, real-provider
AI behavior, whole-computer scan performance and native Wayland interaction still need
validation on target installations. CI runs the core test suite on Linux and Windows and
builds the desktop shell on Linux, macOS and Windows; the release workflow builds and
smoke-tests the bundled core for the Windows and Linux installers. Installing and using
them on real Windows/Linux machines (microphone, WebView2) still needs a manual check.
