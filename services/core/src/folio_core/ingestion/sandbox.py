"""Parse untrusted files in a separate, resource-limited subprocess (proposal: "Security").

A malformed or malicious file can at worst crash or time out the child; the core service keeps
running and the job is marked failed with the cause. File content is only ever *read*.

Child entry point: ``python -I -m folio_core.ingestion.sandbox <parser> <path> <memory-mb>``
(or ``folio-core sandbox ...`` in a frozen build). It lowers its own memory limit before touching
the file and prints the parsed units as JSON on stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from .base import ParseContext, ParsedUnit, ParseError

_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TMP", "TEMP", "TMPDIR")
# One parse needs no thread pools; each BLAS/OpenMP thread would reserve its own buffers.
_SINGLE_THREADED = {k: "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}


def run_sandboxed(parser_name: str, path: Path, timeout_s: int, memory_mb: int) -> list[ParsedUnit]:
    if getattr(sys, "frozen", False):  # PyInstaller build: the binary has a `sandbox` subcommand
        cmd = [sys.executable, "sandbox", parser_name, str(path), str(memory_mb)]
    else:
        cmd = [sys.executable, "-I", "-m", "folio_core.ingestion.sandbox",
               parser_name, str(path), str(memory_mb)]
    env = {k: v for k, v in os.environ.items() if k in _ENV_KEEP} | _SINGLE_THREADED
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW: no console flash
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s, env=env, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise ParseError(f"parser timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        from ..providers.stt.audio import clean_child_error

        raise ParseError(clean_child_error(proc.stderr) or f"parser exited with code {proc.returncode}")
    return [ParsedUnit(**u) for u in json.loads(proc.stdout)]


def child_main(argv: list[str]) -> int:
    parser_name, path, memory_mb = argv[0], Path(argv[1]), int(argv[2])
    if sys.platform != "win32":
        import resource

        limit = memory_mb * 1024 * 1024
        # RLIMIT_DATA (Linux >= 4.7 counts private writable memory incl. anonymous mmaps) caps
        # what a parser can allocate. RLIMIT_AS also counted reserved-but-unused address space
        # (glibc arenas, BLAS buffers, mapped libraries), which could crash the child at import.
        limit_kind = getattr(resource, "RLIMIT_DATA", resource.RLIMIT_AS)
        resource.setrlimit(limit_kind, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    from .registry import ParserRegistry

    units = ParserRegistry().by_name(parser_name).parse(path, ParseContext())
    sys.stdout.write(json.dumps([asdict(u) for u in units], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(child_main(sys.argv[1:]))
