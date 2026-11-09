# Folio for Omarchy

Install the downloadable Arch x86_64 package:

```bash
sudo pacman -U ./folio-desktop-0.2.0-1-x86_64.pkg.tar.zst
```

Open **Folio** in the Omarchy launcher (`Super+Space`) or run `folio` from any folder.
The frontend and Python service are bundled. Node, uv, Rust, Docker, MongoDB and the
source checkout are not needed on the installed machine.

## Your local data

Folio has no developer-operated storage or login service. Each OS user keeps their own
knowledge in `~/.local/share/folio/knowledge.sqlite3` and a rebuildable search/job index
in `~/.local/share/folio/index.db`. These are local files, not network databases.
Startup/runtime logs are in `~/.local/share/folio/logs/core.log`. Your own API keys and
optional Google OAuth credentials are in `secrets.json` with private file permissions.
Set `FOLIO_DATA_DIR` before launching to choose another local storage folder.

Choose **Scan my computer** to select Home, mounted drives, the readable filesystem, or
additional paths. File inventory and supported content indexing run in background jobs;
progress and errors appear in Activity. Hidden folders, exclusions and watching are
optional. Unsupported content formats show **Metadata only**. Symlinks, unreadable files,
virtual system paths and Folio's data folder are skipped. Originals are never modified,
moved or uploaded by scanning. No scan starts just by installing Folio; previously
selected folders are rescanned on later app launches.

## Your AI and Google Drive connections

AI is local by default. In **Settings → AI model**, choose Ollama/local inference or
explicitly choose a hosted provider with your own API key. Hosted AI sends document text
to that provider for processing; working data still remains in your local Folio files.

Google Drive is optional. In **Settings → Google Drive**, import a Desktop OAuth client
JSON from your own Google Cloud project with the Drive API enabled. Use your own Google
account in the system browser. See [Google's Desktop OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app).
Folio uses PKCE and a loopback callback and requests only `drive.file` access to its own
backups. There is no developer OAuth client, shared credential or hosted callback relay.

Choose **Back up now** to copy a JSON knowledge backup to your Drive. It includes facts,
evidence quotes, source paths and history, excludes API keys and original files, and is
never uploaded automatically. Backups remain in your Google account. Use the same OAuth
app to list and restore them on another device; restoring needs an empty local project.
Disconnect removes Drive credentials from this device. You can separately revoke the
OAuth app's permissions in your Google account. Automated checks do not prove live OAuth
without signing in with your actual credentials.

For an offline copy, export JSON from **Settings → Data** to a local folder. Older Folio
JSON exports can be imported into an empty local project; old Docker volumes are never
removed or migrated automatically.

## Runtime and removal

The Arch package declares WebKitGTK, GTK3, OpenSSL and PortAudio dependencies. Optional
`tesseract` enables OCR, and `ffmpeg` enables audio/video parsing. Speech support is
bundled, but its Whisper model downloads only after **Settings → Voice → Download**.

For a portable run, extract `folio-omarchy-x86_64.tar.zst` and run
`./folio-omarchy/folio`. Keep `folio-core` beside it; the same Linux runtime libraries are
required. Uninstalling with `sudo pacman -R folio-desktop` retains all app data and originals.

To build, run `bash scripts/build-omarchy.sh` with Rust, Node, uv, `base-devel`, GTK3,
`webkit2gtk-4.1` and `portaudio` available. It builds an Arch package and portable archive
in `artifacts/` with SHA256 checksums. Building does not install the app or scan your files.
