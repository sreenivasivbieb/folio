"""What Folio never imports: system locations, and junk inside dropped folders."""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

# Smart ignore: skipped silently when a folder is dropped (no configuration needed).
JUNK_DIRS = frozenset(n.lower() for n in (
    ".git", ".svn", ".hg", "node_modules", "bower_components", "venv", ".venv", "env", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "target", "dist", "build", "out", ".next", ".nuxt",
    ".cache", ".idea", ".vscode", "$RECYCLE.BIN", "System Volume Information",
    ".ssh", ".gnupg", ".aws", ".pki",  # credentials: never imported
))
JUNK_FILES = frozenset(n.lower() for n in (
    ".DS_Store", "Thumbs.db", "desktop.ini", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "uv.lock", "Cargo.lock", "poetry.lock", "Pipfile.lock", "composer.lock",
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "DumpStack.log.tmp",
))
JUNK_EXTENSIONS = frozenset((
    ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".a", ".lib", ".pyc", ".pyo", ".class", ".jar",
    ".wasm", ".iso", ".img", ".vmdk", ".vdi", ".qcow2",
))
_SHARED_LIB = re.compile(r"\.so(\.\d+)+$", re.I)  # libfoo.so.6

# Kept for the scanner's per-root exclusion patterns (folder names and file names).
DEFAULT_EXCLUSIONS = sorted(JUNK_DIRS | JUNK_FILES)


def is_junk(path: Path, name: str, is_dir: bool) -> bool:
    """Hidden entries, developer/build/cache folders, lockfiles, binaries and disk images."""
    if is_hidden(path, name):
        return True
    low = name.lower()
    if is_dir:
        return low in JUNK_DIRS
    return (low in JUNK_FILES or Path(low).suffix in JUNK_EXTENSIONS or bool(_SHARED_LIB.search(low)))


def _windows_system_dirs() -> list[Path]:
    root = Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\")
    dirs = [Path(os.environ.get("SYSTEMROOT", root / "Windows")), root / "$Recycle.Bin",
            root / "System Volume Information", root / "Recovery", root / "ProgramData" / "Microsoft",
            Path(os.environ.get("TEMP", root / "Windows" / "Temp"))]
    if local := os.environ.get("LOCALAPPDATA"):
        dirs += [Path(local) / "Temp", Path(local) / "Microsoft", Path(local) / "Packages"]
    return dirs


SYSTEM_EXCLUSIONS = _windows_system_dirs() if sys.platform == "win32" else [
    Path(p) for p in ("/proc", "/sys", "/dev", "/tmp", "/var/lib/docker", "/var/lib/containers", "/var/cache")]


def is_hidden(path: Path, name: str) -> bool:
    """Dot-files everywhere; on Windows also the Hidden/System attributes (AppData, ProgramData)."""
    if name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            attrs = path.lstat().st_file_attributes  # type: ignore[attr-defined]
        except OSError:
            return False
        return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))  # type: ignore[attr-defined]
    return False
