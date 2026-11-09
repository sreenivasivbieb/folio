"""Filesystem locations and scan exclusions, independent of the checkout's location."""

from __future__ import annotations

import os
import re
import stat
import string
import sys
from pathlib import Path

DEFAULT_EXCLUSIONS = [".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
                      ".cache", ".ssh", ".gnupg", ".aws", ".pki",
                      # Windows system/cache entries that are never personal documents
                      "$Recycle.Bin", "System Volume Information", "pagefile.sys", "hiberfil.sys",
                      "swapfile.sys", "DumpStack.log.tmp", "Thumbs.db", "desktop.ini"]


def _windows_system_dirs() -> list[Path]:
    root = Path(os.environ.get("SystemDrive", "C:") + "\\")
    dirs = [Path(os.environ.get("SystemRoot", root / "Windows")), root / "$Recycle.Bin",
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


def windows_drives() -> list[str]:
    try:
        return list(os.listdrives())  # type: ignore[attr-defined]  # Python 3.12+
    except (AttributeError, OSError):
        return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]


def scan_locations(home: Path | None = None, mountinfo: Path = Path("/proc/self/mountinfo")) -> list[dict[str, str]]:
    home = (home or Path.home()).resolve()
    if sys.platform == "win32":
        locations = [{"path": str(home), "label": "Home folder", "kind": "home"}]
        for drive in windows_drives():
            locations.append({"path": drive, "label": f"Drive {drive.rstrip(chr(92))}", "kind": "drive"})
        return locations
    locations = [{"path": str(home), "label": "Home folder", "kind": "home"}]
    seen = {str(home), "/"}
    try:
        lines = mountinfo.read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        parts = line.split()
        if len(parts) < 6 or "-" not in parts:
            continue
        mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), parts[4])
        fs = parts[parts.index("-") + 1]
        if (mount in seen or fs in {"proc", "sysfs", "tmpfs", "devtmpfs", "cgroup2", "squashfs", "overlay"}
                or not any(mount == p or mount.startswith(p + "/") for p in ("/mnt", "/media", "/run/media", "/home"))):
            continue
        seen.add(mount)
        locations.append({"path": mount, "label": Path(mount).name or mount, "kind": "drive"})
    locations.append({"path": "/", "label": "Entire filesystem (readable files)", "kind": "system"})
    return locations
