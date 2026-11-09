#!/usr/bin/env bash
# Build the Python core into one self-contained executable and place it where Tauri's
# `externalBin` expects it: apps/desktop/src-tauri/binaries/folio-core-<target-triple>[.exe]
#
# Users then install one app; no Python needed (proposal: "Packaging").
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE="$ROOT/services/core"
OUT="$ROOT/apps/desktop/src-tauri/binaries"
RUSTC="$(command -v rustc || echo "$HOME/.cargo/bin/rustc")"
[ -x "$RUSTC" ] || { echo "rustc not found (needed for the target triple)" >&2; exit 1; }
TRIPLE="$("$RUSTC" -vV | sed -n 's/^host: //p')"
EXT=""
case "$TRIPLE" in *windows*) EXT=".exe" ;; esac

cd "$CORE"
uv sync --frozen --extra speech --group build
uv run --frozen --extra speech --group build pyinstaller \
  --noconfirm --clean --onefile --name folio-core \
  --collect-data folio_core \
  --collect-all sqlite_vec \
  --collect-all pypdfium2 --collect-all pypdfium2_raw \
  --collect-all faster_whisper --collect-all ctranslate2 \
  --collect-all sounddevice --copy-metadata folio-core \
  --hidden-import uvicorn.logging --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.lifespan.on --hidden-import uvicorn.loops.auto \
  --distpath "$CORE/dist" --workpath "$CORE/build" \
  "$CORE/src/folio_core/__main__.py"

mkdir -p "$OUT"
cp "$CORE/dist/folio-core$EXT" "$OUT/folio-core-$TRIPLE$EXT"
echo "sidecar -> $OUT/folio-core-$TRIPLE$EXT"
