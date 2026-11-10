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
from .locations import is_junk

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
        here = str(self.dir.resolve())
        doc = self.kdb["roots"].find_one({"path": here})
        if doc is None:
            # The data folder moved: adopt the old vault root instead of starting a second one.
            old = next((d for d in self.kdb["roots"].find({"path": {"$regex": r"[\\/]vault$"}})
                        if ".trash" in (d.get("exclude") or [])), None)
            if old is not None:
                with self.ingestion.ledger.group("system", "root.rehome", here) as tx:
                    tx.update("roots", old["_id"], {"path": here})
                doc = self.kdb["roots"].find_one({"_id": old["_id"]})
        if doc is not None:
            return repo.root_from_doc(doc)
        return self.ingestion.add_root(str(self.dir), watch=False, include_hidden=False, exclude=[".trash"])

    def rehome(self) -> int:
        """If Folio's data folder moved (new FOLIO_DATA_DIR, restored backup, different Windows
        profile), stored files keep pointing at the old place. Point them at this vault again,
        so they are not re-added as duplicates and trash/restore/export keep working."""
        fixed = 0
        for d in self.kdb["sources"].find({"path": {"$regex": r"[\\/]vault[\\/](?:\.trash[\\/])?[0-9a-f]{32}[\\/]"}}):
            path = Path(d["path"])
            if self.is_vault_path(path):
                continue
            parts = path.parts
            i = max(k for k, p in enumerate(parts) if p == "vault")
            candidate = self.dir.joinpath(*parts[i + 1:])
            if candidate.exists():
                self.kdb["sources"].update_one({"_id": d["_id"]}, {"$set": {"path": str(candidate)}})
                fixed += 1
        if fixed:
            log.info("re-homed %d stored file(s) to %s", fixed, self.dir)
        return fixed

    def is_vault_path(self, path: Path) -> bool:
        base = self.dir.resolve()
        p = path.resolve()
        return p == base or base in p.parents

    # --- import ----------------------------------------------------------------------------

    def _expand(self, paths: list[str]) -> tuple[list[tuple[Path, Path | None]], int]:
        """(file, the dropped folder it came from or None) for every file worth keeping, and how
        many junk entries were skipped (hidden, node_modules, build output, lockfiles, binaries)."""
        data = self.ingestion.settings.data_dir.resolve()
        out: list[tuple[Path, Path | None]] = []
        skipped = 0
        for raw in paths:
            p = Path(raw).expanduser()
            if not p.exists():
                raise InvalidInput(f"{p} does not exist")
            rp = p.resolve()
            if rp == data or data in rp.parents or rp in data.parents:
                raise InvalidInput("that location is Folio's own storage (or contains it)")
            if p.is_symlink():
                skipped += 1
                continue
            if p.is_file():
                if is_junk(p, p.name, False):
                    skipped += 1
                else:
                    out.append((p, None))
                continue
            for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
                d = Path(dirpath)
                keep = []
                for n in dirnames:
                    if (d / n).is_symlink() or is_junk(d / n, n, True):
                        skipped += _count_files(d / n)
                    else:
                        keep.append(n)
                dirnames[:] = keep
                for n in filenames:
                    f = d / n
                    if f.is_symlink() or not f.is_file() or is_junk(f, n, False):
                        skipped += 1
                    else:
                        out.append((f, p))
        return out, skipped

    def preview(self, paths: list[str]) -> dict[str, int]:
        """How many files a drop will add, and how much junk is skipped (for the drop card)."""
        files, skipped = self._expand(paths)
        return {"files": len(files), "skipped": skipped}

    def _duplicate(self, root_id: str, digest: str) -> dict[str, Any] | None:
        return self.kdb["sources"].find_one({"root_id": root_id, "content_hash": digest, "status": LIVE})

    def import_paths(self, paths: list[str], mode: Mode, drop_id: str | None = None,
                     progress: Callable[[float, str], None] = lambda f, m: None) -> dict[str, Any]:
        """Move/copy ``paths`` into the vault. ``stats["records"]`` lists every file of the drop
        (new or already stored) with its path inside the dropped folder, for drop organizing."""
        if mode not in ("move", "copy"):
            raise InvalidInput("mode must be 'move' or 'copy'")
        from .service import PRIORITY_SELECTED_FILE, file_hash

        root = self.root()
        files, skipped = self._expand(paths)
        stats: dict[str, Any] = {"imported": 0, "duplicates": 0, "failed": 0, "skipped": skipped, "records": []}
        folders: set[Path] = set()
        for i, (src, folder) in enumerate(files):
            if i % 10 == 0:
                progress(i / max(len(files), 1), f"{i} of {len(files)} files")
            try:
                digest = file_hash(src)
                rel = f"{folder.name}/{src.relative_to(folder).as_posix()}" if folder is not None else src.name
                existing = self._duplicate(root.id, digest)
                if existing is not None:
                    stats["duplicates"] += 1  # already in Folio: the original is left untouched
                    stats["records"].append({"source_id": existing["_id"], "rel_path": rel,
                                             "origin_path": str(src.resolve()), "duplicate": True})
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
                try:
                    self.ingestion._track(dest, root.id, PRIORITY_SELECTED_FILE)
                except Exception:
                    # Not recorded: never leave an orphan in the vault. A moved file goes back.
                    if mode == "move" and not origin.exists():
                        shutil.move(str(dest), str(origin))
                    shutil.rmtree(dest.parent, ignore_errors=True)
                    raise OSError(f"could not record {src.name}") from None
                found = repo.source_by_path(self.kdb, str(dest))
                if found is not None:
                    self.kdb["sources"].update_one({"_id": found.id}, {"$set": {
                        "origin_path": str(origin), "drop_id": drop_id,
                        "imported_at": utcnow(), "import_mode": mode, "content_hash": digest}})
                    stats["records"].append({"source_id": found.id, "rel_path": rel,
                                             "origin_path": str(origin), "duplicate": False})
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

    on_imported: Callable[[str, dict[str, Any]], None] | None = None  # set by the drop service

    def import_job(self, job: Any) -> str:
        stats = self.import_paths(job.payload["paths"], job.payload["mode"], job.payload.get("drop_id"),
                                  lambda f, m: self.queue.progress(job.id, f, m))
        if job.payload.get("drop_id") and self.on_imported is not None:
            self.on_imported(job.payload["drop_id"], stats)
        verb = "Moved" if job.payload["mode"] == "move" else "Copied"
        return (f"{verb} {stats['imported']} file(s) into Folio"
                + (f"; {stats['duplicates']} already there (left in place)" if stats["duplicates"] else "")
                + (f"; {stats['failed']} could not be imported" if stats["failed"] else "")
                + (f"; {stats['skipped']} junk file(s) skipped" if stats["skipped"] else ""))

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
            new_path = path
            if folder.exists():  # only point at the trash when the folder really went there
                shutil.move(str(folder), str(target))
                new_path = target / path.name
            self.ingestion._drop_chunks(source_id)
            self.kdb["sources"].update_one({"_id": source_id}, {"$set": {
                "status": SourceStatus.TRASHED.value, "path": str(new_path),
                "trashed_at": utcnow(), "updated_at": utcnow()}})
        self.ingestion._changed(source_id)

    def restore(self, source_id: str) -> None:
        with self.kdb._write_lock:
            src, path = self._vault_source(source_id)
            if src.status != SourceStatus.TRASHED:
                raise InvalidInput("this file is not in the trash")
            target = self.dir / path.parent.name
            if path.parent.exists() and path.parent != target:
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
        if dest_dir:
            folder: Path | None = Path(dest_dir).expanduser()
        elif doc.get("origin_path"):
            folder = Path(doc["origin_path"]).parent
        else:
            folder = None  # never fall back to the working directory
        if folder is None or not folder.is_absolute() or not folder.is_dir():
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


def _count_files(folder: Path, cap: int = 100_000) -> int:
    """Files inside a skipped folder (node_modules can hold tens of thousands): for the summary."""
    n = 0
    for _dirpath, _dirs, files in os.walk(folder, followlinks=False):
        n += len(files)
        if n >= cap:
            break
    return n
