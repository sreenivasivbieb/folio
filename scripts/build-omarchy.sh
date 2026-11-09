#!/usr/bin/env bash
# Build distributable Linux binaries without embedding a source-checkout dependency.
set -euo pipefail
FOLIO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$FOLIO_ROOT"
if ! command -v cargo >/dev/null && [ -x "$FOLIO_ROOT/.build-tools/cargo/bin/cargo" ]; then
  export RUSTUP_HOME="$FOLIO_ROOT/.build-tools/rustup"
  export CARGO_HOME="$FOLIO_ROOT/.build-tools/cargo"
  export PATH="$FOLIO_ROOT/.build-tools/cargo/bin:$PATH"
fi
for tool in cargo rustc uv npm makepkg zstd; do
  command -v "$tool" >/dev/null || { echo "Build tool missing: $tool" >&2; exit 1; }
done
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
npm run build:ui
bash scripts/build-sidecar.sh
(cd apps/desktop/src-tauri && cargo build --release --locked --features tauri/custom-protocol)
FOLIO_STAGE="$FOLIO_ROOT/artifacts/folio-omarchy"
mkdir -p "$FOLIO_STAGE"
install -m755 apps/desktop/src-tauri/target/release/folio-desktop "$FOLIO_STAGE/folio"
FOLIO_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
install -m755 "apps/desktop/src-tauri/binaries/folio-core-$FOLIO_TRIPLE" "$FOLIO_STAGE/folio-core"
install -m644 apps/desktop/src-tauri/icons/128x128.png "$FOLIO_STAGE/folio.png"
install -m644 pkgbuild/folio.desktop pkgbuild/PKGBUILD docs/INSTALL.md "$FOLIO_STAGE/"
python3 - "$FOLIO_STAGE" <<'PY'
from pathlib import Path
import hashlib, sys
folder = Path(sys.argv[1])
names = ['folio', 'folio-core', 'folio.desktop', 'folio.png', 'INSTALL.md']
sums = [hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in names]
pkg = folder / 'PKGBUILD'
pkg.write_text(pkg.read_text().replace("sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP' 'SKIP')",
                                     'sha256sums=(' + ' '.join(repr(s) for s in sums) + ')'))
PY
(cd "$FOLIO_STAGE" && makepkg --force --nodeps --nocheck)
cp "$FOLIO_STAGE/folio-0.2.0-1-x86_64.pkg.tar.zst" artifacts/
tar --zstd -cf artifacts/folio-omarchy-x86_64.tar.zst -C artifacts \
  folio-omarchy/folio folio-omarchy/folio-core folio-omarchy/folio.png folio-omarchy/INSTALL.md
(cd artifacts && sha256sum folio-0.2.0-1-x86_64.pkg.tar.zst folio-omarchy-x86_64.tar.zst > SHA256SUMS)
echo "Built artifacts/folio-0.2.0-1-x86_64.pkg.tar.zst and artifacts/folio-omarchy-x86_64.tar.zst"
