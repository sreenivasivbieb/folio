# Folio

[![CI](https://github.com/sreenivasivbieb/folio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sreenivasivbieb/folio/actions/workflows/ci.yml)

**Drop your files, say what they are, and find everything later.**

Folio is a desktop workspace for **Windows and Linux** (including Omarchy/Arch) built
around one loop:

**Drop → Label (voice or text) → AI organizes → Graph & Search**

1. **Drop** files or a whole project folder onto the window. Folio never scans your
   computer, and it silently skips junk such as `node_modules`, `.git`, build output,
   lockfiles and binaries.
2. **Label** the drop in your own words — type it, or hold to speak in English, Hindi
   or Hinglish.
3. **The AI organizes** it from your label: a project, a short summary, folders for the
   files, tags, and the people, organisations and dates you mentioned. Without an AI
   model, offline rules do the same from your label and the folder layout.
4. **Explore and search** a clean graph of projects, folders, files, people and topics,
   and search by what you said, by project, by name, or by the text inside any file.

Your files and knowledge stay in private local files on your machine. Choose offline
processing, a local AI model, or a cloud AI provider with your own API key. Optional
Google Drive backup uses your own Google account and OAuth credentials.

[Install](#install) · [First drop](#your-first-drop) ·
[Storage](#your-data-and-privacy) · [AI](#choose-your-ai) ·
[Google Drive](#optional-google-drive-backup) · [Development](#development)

## What you can do

- **Drop & Label:** drop files or a project folder (or pick them), see how many files
  will be added and how much junk is skipped, choose **Move** (files then live only in
  Folio — no duplicate disk space) or **Copy**, then describe them by voice or text.
- **Organize with AI:** one click turns your label into a project with a summary,
  folders, tags, people and organisations. Re-label any time; Ctrl+Z undoes it.
- **Projects:** every organized drop as a project — your original label, the AI
  summary, people and tags, and the files grouped by folder. Optionally **Preview &
  organize on disk** to move the original files into those folders (Copy drops only;
  nothing moves until you confirm, and it can be undone).
- **Graph:** projects, folders, files, people and topics, linked. Focus on a project,
  person or tag, and highlight anything by name.
- **Search everything** (`/` or Ctrl+K): your labels and project summaries first, then
  project, tag and file names (typos and partial words are fine), then exact passages
  with page numbers, lines or audio/video timestamps.
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
| `folio-desktop-0.2.0-1-x86_64.pkg.tar.zst` | Arch package with launcher entry and runtime dependencies |
| `folio-omarchy-x86_64.tar.zst` | Portable desktop app and bundled core service |
| `SHA256SUMS` | Checksums for both artifacts |

### Install and launch

From the `artifacts/` folder:

```bash
sha256sum --check SHA256SUMS
sudo pacman -U ./folio-desktop-0.2.0-1-x86_64.pkg.tar.zst
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

## Your first drop

1. Open Folio. The **Drop & Label** screen is the home screen.
2. Drop files or a project folder onto the window, or use **Choose files** /
   **Choose a folder**. Folio shows how many files it will add and how many junk files
   it skips.
3. Choose **Move** or **Copy**, then **Add**.
4. Say or type what the files are — for example *"Final architecture docs, datasets and
   meeting notes with Rahul for the Pune Solar project"*. **Hold to speak** fills the
   box with your words so you can check them first.
5. Click **Organize with AI**. The result shows the project, summary, folders, people
   and tags; open it in **Projects** or view it in the **Graph**.

Skipped automatically when you drop a folder: hidden files and folders, `.git`, `.svn`,
`.hg`, `node_modules`, `bower_components`, virtual environments (`venv`, `.venv`,
`env`), caches (`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.cache`),
build output (`target`, `dist`, `build`, `out`, `.next`, `.nuxt`), editor folders,
lockfiles, binaries (`.exe`, `.dll`, `.so`, `.dylib`, `.o`, `.pyc`, `.class`, `.jar`,
`.wasm`) and disk images (`.iso`, `.img`, `.vmdk`). Supported formats get content
indexing; other formats are kept as **Metadata only**.

### Supported content

| File family | Extensions | Processing |
| --- | --- | --- |
| Text and Markdown | `.txt`, `.md`, `.markdown` | Text extraction with line references |
| PDF | `.pdf` | Text extraction; scanned pages use optional Tesseract OCR |
| Word | `.docx` | Document text extraction |
| Subtitles | `.srt`, `.vtt` | Text with timestamps |
| Images | `.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`, `.bmp`, `.gif` | Optional OCR; basic image details when text is unavailable |
| Audio | `.mp3`, `.wav`, `.m4a`, `.ogg`, `.oga`, `.opus`, `.flac`, `.aac`, `.wma` | Transcription with timestamps (offline model, or your provider's Whisper) |
| Video | `.mp4`, `.mkv`, `.mov`, `.webm`, `.avi`, `.m4v`, `.wmv` | Transcription of the audio track (videos without audio are kept as-is) |

OCR requires Tesseract with English language data (optional on every platform).
Audio/video transcription uses your connected Groq/OpenAI account, or the offline speech
model you download once in **Settings → Voice** (~480 MB). Decoding is built in — no
ffmpeg needed.

## Your data and privacy

**Folio has no developer-operated storage service, shared database or required Folio
account.** Each operating-system user has their own local app data.

On Linux, the default folder is `~/.local/share/folio/`, or `$XDG_DATA_HOME/folio/`
when `XDG_DATA_HOME` is set:

| Local file or folder | Contents |
| --- | --- |
| `vault/` | Files you dropped into Folio (moved or copied), and Folio's trash |
| `knowledge.sqlite3` | Drops, labels, projects, entities, links, settings and undo history |
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
| Default offline processing | Rule-based organizing and search run on this device |
| Local AI endpoint | Document text goes to the local model server you configure |
| Hosted AI provider | Your labels, file names and short text snippets are sent to your chosen provider using your key; with voice through the provider, label audio is too |
| Google Drive **Back up now** | A knowledge backup is uploaded to your Google account |

Credentials are excluded from knowledge exports and Drive backups. Backups can contain
document excerpts, source paths and history, so choose their destination accordingly.
Removing the app retains your local app data (including files you moved into Folio's
vault) and any originals you copied from.

## Choose your AI

Folio works without an AI account: offline rules organize each drop from your label
and the folder layout. A connected model understands any phrasing and organizes better.

In **Settings → AI model**:

1. Choose **Ollama** for a model running on this computer, or a custom local
   OpenAI-compatible endpoint. Start your local model server separately.
2. Alternatively, choose a hosted preset such as OpenRouter, OpenAI, Qwen or Groq,
   or enter a custom compatible URL, and supply your own API key.
3. Use **Load models**, select an available model, and **Save**. Use **Test** to check
   the connection.

With Groq or OpenAI connected, voice labels also work right away through the provider's
Whisper; download the offline speech model in **Settings → Voice** to keep audio on
your computer. Free tiers rate-limit requests: Folio waits and retries instead of failing.

Saving a hosted endpoint enables cloud processing for the project. The top bar shows
**Local AI** or **Cloud AI**. Disable cloud processing in **Settings → Privacy**.
Working knowledge remains in your local Folio files with either choice.

Deep fact extraction (every person and fact in every passage, for review) is off by
default; run it on demand with **Settings → Data → Re-run extraction**.

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
reopen them. **Disconnect locally** removes this device's Drive credentials.
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
| Fewer files were added than you dropped | Junk (hidden, `node_modules`, build output, lockfiles, binaries) is skipped on purpose — the drop card shows the count; duplicates already in Folio are reused |
| A drop stays "Organizing…" | A rate-limited AI provider is being waited on; without a reply Folio falls back to offline rules. See Activity |
| "Organize on disk" is disabled | It needs a single folder dropped with **Copy**; moved files live in Folio — use Export first |
| A file says **Metadata only** | Its format has no content parser; its path and metadata are still inventoried |
| Images or scanned PDFs have no extracted text | Check Tesseract and its English language data |
| Audio/video has no transcript | Connect Groq/OpenAI or download the speech model (Settings → Voice); videos without an audio track are kept without one |
| Voice: nothing happens on Wayland | Apps can't grab global keys there: bind a desktop shortcut to `folio-core voice toggle` (Settings → Voice) |
| Voice: a name is misheard | Click **Edit** in the label preview, fix the text, **Re-check** |
| AI connection fails | Check the local server or hosted provider URL, model and your API key; use **Test** |
| Drive restore is unavailable | Restore into an empty project using the OAuth client that created the backup |

The Omarchy x86_64 package has been built and checked with generated sample files,
and the drop → label → organize → graph flow has been exercised end to end in a browser
against a real hosted model (Groq). Live Google sign-in, native file drag-and-drop in the
desktop window, and native Wayland interaction still need validation on target
installations. CI runs the core test suite on Linux and Windows and
builds the desktop shell on Linux, macOS and Windows; the release workflow builds and
smoke-tests the bundled core for the Windows and Linux installers. Installing and using
them on real Windows/Linux machines (microphone, WebView2) still needs a manual check.
