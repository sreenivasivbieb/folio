"""The vault: files the user dumps into Folio live in Folio's own data folder.

    <data_dir>/vault/<token>/<original name>          stored files (one folder each: names never clash)
    <data_dir>/vault/.trash/<token>/<original name>   trashed files (restorable)

Importing either MOVES a file in (it then exists only here: no duplicate disk use) or COPIES it,
as the user chooses each time. Folio never scans the rest of the computer. Each stored file is a
normal source of the vault root, so indexing, search, labels and evidence work unchanged.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from ..domain.errors import InvalidInput, NotFound
from ..domain.models import Root, SourceStatus
from ..store import repo
from ..store.index_db import utcnow
from .locations import DEFAULT_EXCLUSIONS, is_hidden

log = logging.getLogger(__name__)

Mode = Literal["move", "copy"]
LIVE = {"$nin": ["trashed", "forgotten", "removed"]}


class Vault:
    def __init__(self, ingestion: Any) -> None:  # IngestionService (avoids an import cycle)
        self.ingestion = ingestion
        self.kdb = ingestion.kdb
        self.queue = ingestion.queue
        self.dir = ingestion.settings.data_dir / "vault"
        self.trash_dir = self.dir / ".trash"

    # --- root ------------------------------------------------------------------------------

    def root(self) -> Root:
        """The single root Folio indexes: its own vault folder (never the user's computer)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.dir.chmod(0o700)
        doc = self.kdb["roots"].find_one({"path": str(self.dir.resolve())})
        if doc is not None:
            return repo.root_from_doc(doc)
        return self.ingestion.add_root(str(self.dir), watch=False, include_hidden=False, exclude=[".trash"])

    def is_vault_path(self, path: Path) -> bool:
        base = self.dir.resolve()
        p = path.resolve()
        return p == base or base in p.parents

    # --- import ----------------------------------------------------------------------------

    def _expand(self, paths: list[str]) -> list[tuple[Path, Path | None]]:
        """(file, the imported folder it came from or None). Skips hidden, cache and link entries."""
        data = self.ingestion.settings.data_dir.resolve()
        out: list[tuple[Path, Path | None]] = []
        for raw in paths:
            p = Path(raw).expanduser()
            if not p.exists():
                raise InvalidInput(f"{p} does not exist")
            rp = p.resolve()
            if rp == data or data in rp.parents or rp in data.parents:
                raise InvalidInput("that location is Folio's own storage (or contains it)")
            if p.is_symlink():
                continue
            if p.is_file():
                out.append((p, None))
                continue
            for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
                d = Path(dirpath)
                dirnames[:] = [n for n in dirnames if not is_hidden(d / n, n) and n not in DEFAULT_EXCLUSIONS
                               and not (d / n).is_symlink()]
                for n in filenames:
                    f = d / n
                    if not is_hidden(f, n) and n not in DEFAULT_EXCLUSIONS and not f.is_symlink() and f.is_file():
                        out.append((f, p))
        return out

    def _duplicate(self, root_id: str, digest: str) -> bool:
        return self.kdb["sources"].find_one({"root_id": root_id, "content_hash": digest, "status": LIVE}) is not None

    def import_paths(self, paths: list[str], mode: Mode,
                     progress: Callable[[float, str], None] = lambda f, m: None) -> dict[str, int]:
        if mode not in ("move", "copy"):
            raise InvalidInput("mode must be 'move' or 'copy'")
        from .service import PRIORITY_SELECTED_FILE, file_hash

        root = self.root()
        files = self._expand(paths)
        stats = {"imported": 0, "duplicates": 0, "failed": 0}
        folders: set[Path] = set()
        for i, (src, folder) in enumerate(files):
            if i % 10 == 0:
                progress(i / max(len(files), 1), f"{i} of {len(files)} files")
            try:
                digest = file_hash(src)
                if self._duplicate(root.id, digest):
                    stats["duplicates"] += 1  # already in Folio: the original is left untouched
                    continue
                origin = src.resolve()
                dest = self.dir / uuid.uuid4().hex / src.name
                dest.parent.mkdir(parents=True)
                try:
                    if mode == "move":
                        shutil.move(str(src), str(dest))  # rename on one disk; copy + delete across disks
                    else:
                        shutil.copy2(src, dest)
                except OSError:
                    # Disk full, unplugged drive...: drop the partial copy. If the original is
                    # gone the move did complete (only cleanup failed), so keep the stored file.
                    if src.exists():
                        shutil.rmtree(dest.parent, ignore_errors=True)
                    raise
                if folder is not None:
                    folders.add(folder)
                self.ingestion._track(dest, root.id, PRIORITY_SELECTED_FILE)
                found = repo.source_by_path(self.kdb, str(dest))
                if found is not None:
                    self.kdb["sources"].update_one({"_id": found.id}, {"$set": {
                        "origin_path": str(origin),
                        "imported_at": utcnow(), "import_mode": mode, "content_hash": digest}})
                stats["imported"] += 1
            except OSError as exc:
                log.warning("could not import %s: %s", src, exc)
                stats["failed"] += 1
        if mode == "move":
            for folder in folders:  # remove the now-empty folders the user dumped
                _prune_empty(folder)
        self.ingestion.bus.publish({"type": "source"})
        progress(1, f"{stats['imported']} added · {stats['duplicates']} already in Folio · {stats['failed']} failed")
        return stats

    def import_job(self, job: Any) -> str:
        stats = self.import_paths(job.payload["paths"], job.payload["mode"],
                                  lambda f, m: self.queue.progress(job.id, f, m))
        verb = "Moved" if job.payload["mode"] == "move" else "Copied"
        return (f"{verb} {stats['imported']} file(s) into Folio"
                + (f"; {stats['duplicates']} already there (left in place)" if stats["duplicates"] else "")
                + (f"; {stats['failed']} could not be imported" if stats["failed"] else ""))

    # --- trash, restore, delete, export ------------------------------------------------------

    def _vault_source(self, source_id: str) -> tuple[Any, Path]:
        src = repo.get_source(self.kdb, source_id)
        if src is None:
            raise NotFound(f"file {source_id} not found")
        path = Path(src.path)
        if not self.is_vault_path(path):
            raise InvalidInput("this file is not stored in Folio")
        return src, path

    def trash(self, source_id: str) -> None:
        with self.kdb._write_lock:
            src, path = self._vault_source(source_id)
            if src.status == SourceStatus.TRASHED:
                return
            folder = path.parent
            target = self.trash_dir / folder.name
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            if folder.exists():
                shutil.move(str(folder), str(target))
            self.ingestion._drop_chunks(source_id)
            self.kdb["sources"].update_one({"_id": source_id}, {"$set": {
                "status": SourceStatus.TRASHED.value, "path": str(target / path.name),
                "trashed_at": utcnow(), "updated_at": utcnow()}})
        self.ingestion._changed(source_id)

    def restore(self, source_id: str) -> None:
        with self.kdb._write_lock:
            src, path = self._vault_source(source_id)
            if src.status != SourceStatus.TRASHED:
                raise InvalidInput("this file is not in the trash")
            target = self.dir / path.parent.name
            if path.parent.exists():
                shutil.move(str(path.parent), str(target))
            self.kdb["sources"].update_one({"_id": source_id}, {
                "$set": {"status": SourceStatus.PENDING.value, "path": str(target / path.name),
                         "indexed_hash": None, "updated_at": utcnow()},
                "$unset": {"trashed_at": 1}})
        self.queue.enqueue("index_source", {"source_id": source_id}, dedupe_key=f"index:{source_id}", priority=10)
        self.ingestion._changed(source_id)

    def delete_forever(self, source_id: str) -> None:
        _src, path = self._vault_source(source_id)
        self.ingestion.forget_source(source_id)  # drops passages and unverified facts; flags verified ones
        shutil.rmtree(path.parent, ignore_errors=True)

    def empty_trash(self) -> int:
        ids = [d["_id"] for d in self.kdb["sources"].find({"status": SourceStatus.TRASHED.value}, {"_id": 1})]
        for sid in ids:
            self.delete_forever(sid)
        return len(ids)

    def export(self, source_id: str, dest_dir: str | None, mode: Mode) -> str:
        """Put a stored file back on the computer: to ``dest_dir`` or where it originally came from.
        Moving it out removes it from Folio; copying keeps it here too."""
        src, path = self._vault_source(source_id)
        doc = self.kdb["sources"].find_one({"_id": source_id}) or {}
        folder = Path(dest_dir).expanduser() if dest_dir else Path(doc.get("origin_path") or "").parent
        if not str(folder) or not folder.is_dir():
            raise InvalidInput("choose a folder to export to")
        if self.is_vault_path(folder):
            raise InvalidInput("choose a folder outside Folio's storage")
        target = _free_name(folder / path.name)
        if mode == "move":
            shutil.move(str(path), str(target))
            self.ingestion.forget_source(source_id)
            shutil.rmtree(path.parent, ignore_errors=True)
        else:
            shutil.copy2(path, target)
        return str(target)

    def trash_list(self) -> list[dict[str, Any]]:
        return [{"id": d["_id"], "name": Path(d["path"]).name, "kind": d.get("kind"), "size": d.get("size", 0),
                 "trashed_at": d.get("trashed_at"), "origin_path": d.get("origin_path")}
                for d in self.kdb["sources"].find({"status": SourceStatus.TRASHED.value}).sort("trashed_at", -1)]


def _free_name(target: Path) -> Path:
    """Never overwrite: report.pdf -> report (1).pdf."""
    n = 1
    candidate = target
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


def _prune_empty(folder: Path) -> None:
    for dirpath, _dirs, _files in os.walk(folder, topdown=False):
        with contextlib.suppress(OSError):
            Path(dirpath).rmdir()  # only succeeds when empty (hidden files keep a folder)
