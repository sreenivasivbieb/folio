"""Filesystem locations and scan exclusions, independent of the checkout's location."""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_EXCLUSIONS = [".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
                      ".cache", ".ssh", ".gnupg", ".aws", ".pki"]
SYSTEM_EXCLUSIONS = [Path(p) for p in ("/proc", "/sys", "/dev", "/tmp", "/var/lib/docker",
                                      "/var/lib/containers", "/var/cache")]


def scan_locations(home: Path | None = None, mountinfo: Path = Path("/proc/self/mountinfo")) -> list[dict[str, str]]:
    home = (home or Path.home()).resolve()
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
