"""Ingestion orchestration: selected roots -> sources -> chunks (+ FTS + vectors).

Flow for one file (FR-1, FR-2):

    scan -> source document (path, size, mtime) -> job "index_source"
         -> content hash unchanged?  -> stop (zero parser and model calls)
         -> parse (sandboxed; media reports transcription progress) -> chunk -> embed
            (reusing vectors of unchanged chunks) -> replace chunks in index.db
         -> job "extract_source"

Originals are opened read-only and never copied, moved or modified.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
from collections.abc import Callable, Iterator
from fnmatch import fnmatch
from pathlib import Path

import numpy as np

from ..config import Settings
from ..domain.errors import InvalidInput, NotFound, Unavailable
from ..domain.ids import new_id
from ..domain.models import ClaimStatus, Root, Source, SourceKind, SourceStatus
from ..jobs import Job, JobQueue
from ..ledger import Ledger
from ..providers.embeddings.base import Embedder
from ..providers.stt.base import Transcriber
from ..realtime import Bus
from ..store import repo
from ..store.index_db import IndexDB, dumps, utcnow
from ..store.local import KnowledgeDB
from ..store.vectors import VectorIndex
from .base import ParseContext
from .chunker import chunk_units
from .locations import DEFAULT_EXCLUSIONS, SYSTEM_EXCLUSIONS, is_hidden
from .registry import ParserRegistry
from .sandbox import run_sandboxed

log = logging.getLogger(__name__)

PRIORITY_SELECTED_FILE = 10  # "selected files first" (risk: slow indexing of long videos)
PRIORITY_WATCH_CHANGE = 5
PRIORITY_FOLDER_SCAN = 0
MEDIA = (SourceKind.AUDIO.value, SourceKind.VIDEO.value)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class IngestionService:
    def __init__(self, *, kdb: KnowledgeDB, index: IndexDB, ledger: Ledger, queue: JobQueue,
                 bus: Bus, registry: ParserRegistry, embedder: Embedder, vectors: VectorIndex,
                 transcriber: Transcriber, settings: Settings,
                 vocabulary: Callable[[], str | None] = lambda: None) -> None:
        self.kdb = kdb
        self.index = index
        self.ledger = ledger
        self.queue = queue
        self.bus = bus
        self.registry = registry
        self.embedder = embedder
        self.vectors = vectors
        self.transcriber = transcriber
        self.settings = settings
        self.vocabulary = vocabulary

    def _changed(self, source_id: str) -> None:
        self.bus.publish({"type": "source", "source_id": source_id})

    # --- roots ----------------------------------------------------------------------------

    def add_root(self, path: str, watch: bool = True, include_hidden: bool = False,
                 exclude: list[str] | None = None) -> Root:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise InvalidInput(f"{p} does not exist")
        existing = self.kdb["roots"].find_one({"path": str(p)})
        if existing:
            root = repo.root_from_doc(existing)
            self.kdb["roots"].update_one({"_id": root.id}, {"$set": {
                "watch": watch, "include_hidden": include_hidden,
                "exclude": DEFAULT_EXCLUSIONS if exclude is None else exclude}})
            root = repo.root_from_doc(self.kdb["roots"].find_one({"_id": root.id}))
        else:
            with self.ledger.group("user", "root.add", str(p)) as tx:
                row = tx.insert("roots", {
                    "id": new_id("root"), "path": str(p), "kind": "file" if p.is_file() else "folder",
                    "watch": watch, "created_at": utcnow(), "include_hidden": include_hidden,
                    "exclude": DEFAULT_EXCLUSIONS if exclude is None else exclude,
                })
            root = Root(**row)
        self.queue.enqueue("scan_root", {"root_id": root.id}, dedupe_key=f"scan:{root.id}", priority=20)
        return root

    def remove_root(self, root_id: str) -> int:
        with self.kdb._write_lock:
            return self._remove_root(root_id)

    def _remove_root(self, root_id: str) -> int:
        """Stop tracking a file/folder. Its knowledge stays; its files leave the list and the
        search index (derived data). Adding the folder again brings them back."""
        with self.ledger.group("user", "root.remove") as tx:
            if tx.delete("roots", root_id) is None:
                raise NotFound(f"root {root_id} not found")
        ids = [d["_id"] for d in self.kdb["sources"].find({"root_id": root_id}, {"_id": 1})]
        for sid in ids:
            self._drop_chunks(sid)
        self.kdb["sources"].update_many({"_id": {"$in": ids}},
                                        {"$set": {"status": SourceStatus.REMOVED.value, "indexed_hash": None,
                                                  "updated_at": utcnow()}})
        self.bus.publish({"type": "source"})
        return len(ids)

    def roots(self) -> list[Root]:
        return repo.list_roots(self.kdb)

    # --- scanning -------------------------------------------------------------------------

    def _excluded(self, path: Path, root: Root) -> bool:
        resolved = path.resolve()
        data = self.settings.data_dir.resolve()
        base = Path(root.path).resolve()
        vault = data / "vault"
        # Folio's own data is never indexed — except the vault, where dumped files live.
        in_vault = resolved == vault or vault in resolved.parents
        # A system folder is skipped while scanning around it, but a folder the user added that
        # lives inside one (e.g. under /tmp or %TEMP%) is still indexed.
        if (not in_vault and (resolved == data or data in resolved.parents)) or any(
                (resolved == p or p in resolved.parents) and not (base == p or p in base.parents)
                for p in SYSTEM_EXCLUSIONS):
            return True
        return any(fnmatch(path.name, pattern) or fnmatch(str(path), pattern) for pattern in root.exclude)

    def _iter_files(self, root: Root, on_error: Callable[[OSError], None] | None = None) -> Iterator[Path]:
        base = Path(root.path)
        if root.kind == "file":
            if base.is_file() and not self._excluded(base, root):
                yield base
            return
        # Roots nested inside this one (e.g. /home/me inside /) are scanned by their own job with
        # their own settings. Walking them twice doubled the work and made files flip roots.
        nested = {Path(r.path) for r in self.roots()
                  if r.id != root.id and Path(r.path) != base and base in Path(r.path).parents}
        for dirpath, dirnames, filenames in os.walk(base, onerror=on_error, followlinks=False):
            d = Path(dirpath)
            dirnames[:] = [n for n in dirnames if (root.include_hidden or not is_hidden(d / n, n))
                          and (d / n) not in nested
                          and not (d / n).is_symlink() and not self._excluded(d / n, root)
                          and (d != Path("/run") or n == "media")]
            for n in filenames:
                p = d / n
                if p in nested:
                    continue
                if ((root.include_hidden or not is_hidden(p, n)) and not p.is_symlink()
                        and not self._excluded(p, root) and p.is_file()):
                    if not os.access(p, os.R_OK):
                        if on_error:
                            on_error(PermissionError(errno.EACCES, "cannot read", str(p)))
                        continue
                    yield p

    def scan_root(self, root: Root, job: Job | None = None) -> int:
        priority = PRIORITY_SELECTED_FILE if root.kind == "file" else PRIORITY_FOLDER_SCAN
        visited = 0
        queued = 0
        unreadable = 0
        metadata = 0

        blocked: list[Path] = []  # unreadable paths: files below them may only *look* deleted
        blind = False  # an error without a path: we cannot tell where we could not look

        def failed(exc: OSError) -> None:
            nonlocal unreadable, blind
            unreadable += 1
            if exc.filename:
                blocked.append(Path(exc.filename))
            else:
                blind = True
            log.warning("scan skipped an unreadable path: %s", exc)

        for f in self._iter_files(root, failed):
            if job and visited % 100 == 0:
                if self.kdb["roots"].find_one({"_id": root.id}) is None:
                    return queued
                self.queue.progress(job.id, 0, f"{visited} files visited; {queued} queued; {metadata} metadata only; {unreadable} unreadable")
            visited += 1
            try:
                queued += self._track(f, root.id, priority)
                metadata += int(not self.registry.supports(f))
            except OSError as exc:
                failed(exc)
        # Files that disappeared from a folder root are marked missing (their knowledge stays).
        for d in self.kdb["sources"].find({"root_id": root.id, "status": {"$nin": ["missing", "forgotten", "removed"]}}):
            path = Path(d["path"])
            if blind or any(path == b or b in path.parents for b in blocked):
                continue  # we could not see there; absence proves nothing
            if not path.exists():
                repo.set_source_status(self.kdb, d["_id"], SourceStatus.MISSING)
                self._changed(d["_id"])
        if job:
            self.queue.progress(job.id, 1, f"{visited} files visited; {queued} queued; {metadata} metadata only; {unreadable} unreadable")
        return queued

    def scan_root_job(self, job: Job) -> str:
        doc = self.kdb["roots"].find_one({"_id": job.payload["root_id"]})
        if doc is None:
            return "cancelled: folder no longer tracked"
        root = repo.root_from_doc(doc)
        queued = self.scan_root(root, job)
        progress = self.queue.get(job.id)
        return "Scan complete: " + (progress.message or f"{queued} file(s) queued for content indexing")

    def _root_for(self, path: Path) -> Root | None:
        """The most specific tracked root containing ``path`` (roots may be nested)."""
        best: Root | None = None
        for root in self.roots():
            rp = Path(root.path)
            if (path == rp or rp in path.parents) and (best is None or len(rp.parts) > len(Path(best.path).parts)):
                best = root
        return best

    def scan_path(self, path: Path) -> None:
        """Called by the folder watcher for one changed path."""
        path = path.resolve()
        root = self._root_for(path)
        if root is None:
            return
        if path.is_file() and not self._excluded(path, root):
            self._track(path, root.id, PRIORITY_WATCH_CHANGE)
        elif not path.exists():
            src = repo.source_by_path(self.kdb, str(path))
            if src and src.status not in (SourceStatus.FORGOTTEN, SourceStatus.REMOVED, SourceStatus.TRASHED):
                repo.set_source_status(self.kdb, src.id, SourceStatus.MISSING)
                self._changed(src.id)

    def rescan_all(self) -> int:
        return sum(bool(self.queue.enqueue("scan_root", {"root_id": r.id}, dedupe_key=f"scan:{r.id}", priority=20))
                   for r in self.roots())

    def _track(self, path: Path, root_id: str, priority: int) -> int:
        with self.kdb._write_lock:
            return self._track_locked(path, root_id, priority)

    def _track_locked(self, path: Path, root_id: str, priority: int) -> int:
        """Upsert the source; queue indexing if the file is new or its size/mtime changed."""
        found = self.registry.for_path(path)
        kind = found[1] if found else SourceKind.OTHER
        st = path.stat()
        now = utcnow()
        src = repo.source_by_path(self.kdb, str(path))
        if src is None:
            src_id = new_id("source")
            self.kdb["sources"].insert_one({
                "_id": src_id, "root_id": root_id, "path": str(path), "kind": kind.value,
                "size": st.st_size, "mtime": st.st_mtime, "content_hash": None, "indexed_hash": None,
                "status": SourceStatus.PENDING.value if found else SourceStatus.METADATA.value,
                "error": None, "priority": priority,
                "created_at": now, "updated_at": now,
            })
        else:
            src_id = src.id
            if src.status in (SourceStatus.FORGOTTEN, SourceStatus.TRASHED):
                return 0  # the user forgot or trashed this file
            if (src.size == st.st_size and src.mtime == st.st_mtime
                    and src.status in (SourceStatus.INDEXED, SourceStatus.METADATA, SourceStatus.INDEXING)):
                return 0  # nothing changed (an index job already in flight sees the same file)
            self.kdb["sources"].update_one({"_id": src_id}, {
                "$set": {"root_id": root_id, "status": SourceStatus.PENDING.value if found else SourceStatus.METADATA.value,
                         "size": st.st_size, "mtime": st.st_mtime, "error": None, "updated_at": now},
                "$max": {"priority": priority},
            })
        if found is None:
            return 0
        self._changed(src_id)
        job = self.queue.enqueue("index_source", {"source_id": src_id},
                                 dedupe_key=f"index:{src_id}", priority=priority)
        return 1 if job else 0

    def requeue_media(self) -> int:
        """After the speech model is downloaded: index the audio/video that was waiting for it."""
        n = 0
        for d in self.kdb["sources"].find({"kind": {"$in": list(MEDIA)}, "status": {"$in": ["failed", "pending"]}}):
            if self.queue.enqueue("index_source", {"source_id": d["_id"]}, dedupe_key=f"index:{d['_id']}",
                                  priority=d.get("priority", 0)):
                n += 1
        return n

    # --- indexing (job handler) -----------------------------------------------------------

    def index_source(self, job: Job) -> str:
        with self.kdb._write_lock:
            src = repo.get_source(self.kdb, job.payload["source_id"])
            if src is None or src.status in (SourceStatus.FORGOTTEN, SourceStatus.REMOVED, SourceStatus.METADATA,
                                             SourceStatus.TRASHED):
                return "skipped: source no longer tracked or has metadata only"
            repo.set_source_status(self.kdb, src.id, SourceStatus.INDEXING)
        path = Path(src.path)
        if not path.exists():
            with self.kdb._write_lock:
                current = repo.get_source(self.kdb, src.id)
                if current and current.status == SourceStatus.INDEXING:
                    repo.set_source_status(self.kdb, src.id, SourceStatus.MISSING)
            self._changed(src.id)
            return "file missing"
        self._changed(src.id)
        try:
            st = path.stat()
            self.queue.progress(job.id, 0.01, "hashing")
            digest = file_hash(path)
        except OSError as exc:
            with self.kdb._write_lock:
                current = repo.get_source(self.kdb, src.id)
                if current and current.status == SourceStatus.INDEXING:
                    repo.set_source_status(self.kdb, src.id, SourceStatus.FAILED, error=str(exc)[:1000])
            self._changed(src.id)
            raise
        if digest == src.indexed_hash and self._has_chunks(src.id):
            with self.kdb._write_lock:
                current = repo.get_source(self.kdb, src.id)
                if current is None or current.status != SourceStatus.INDEXING:
                    return "cancelled: source changed or is no longer tracked"
                repo.set_source_status(self.kdb, src.id, SourceStatus.INDEXED, size=st.st_size,
                                       mtime=st.st_mtime, content_hash=digest)
            self._changed(src.id)
            return "unchanged (content hash match): nothing to do"
        try:
            units = self._parse(path, job)
            drafts = chunk_units(units)
            self.queue.progress(job.id, 0.96, f"{len(drafts)} chunks; embedding")
            if not self._commit_index(src, drafts, st, digest):
                return "cancelled: source changed or is no longer tracked"
        except Unavailable as exc:
            if src.kind.value not in MEDIA:
                self._failed(src.id, exc)
                raise
            # Audio/video waiting for the speech model is not an error: it stays pending and
            # requeue_media() picks it up as soon as the model is downloaded.
            with self.kdb._write_lock:
                current = repo.get_source(self.kdb, src.id)
                if current and current.status == SourceStatus.INDEXING:
                    repo.set_source_status(self.kdb, src.id, SourceStatus.PENDING, error=str(exc)[:1000])
            self._changed(src.id)
            return "waiting for the speech model (Settings → Voice)"
        except Exception as exc:
            self._failed(src.id, exc)
            raise
        return f"indexed {len(drafts)} chunks"

    def _failed(self, source_id: str, exc: Exception) -> None:
        with self.kdb._write_lock:
            current = repo.get_source(self.kdb, source_id)
            if current and current.status == SourceStatus.INDEXING:
                repo.set_source_status(self.kdb, source_id, SourceStatus.FAILED, error=str(exc)[:1000])
        self._changed(source_id)

    def _commit_index(self, src: Source, drafts, st, digest: str) -> bool:  # type: ignore[no-untyped-def]
        # Parsing stays outside the lock. Forget/remove and this short commit cannot interleave.
        with self.kdb._write_lock:
            current = repo.get_source(self.kdb, src.id)
            if current is None or current.status != SourceStatus.INDEXING:
                return False
            self._store_chunks(src, drafts)
            repo.set_source_status(self.kdb, src.id, SourceStatus.INDEXED, size=st.st_size,
                                   mtime=st.st_mtime, content_hash=digest, indexed_hash=digest)
            self._changed(src.id)
            priority = (self.kdb["sources"].find_one({"_id": src.id}, {"priority": 1}) or {}).get("priority", 0)
            self.queue.enqueue("extract_source", {"source_id": src.id}, dedupe_key=f"extract:{src.id}", priority=priority)
            return True

    def _parse(self, path: Path, job: Job):  # type: ignore[no-untyped-def]
        found = self.registry.for_path(path)
        if found is None:
            raise InvalidInput(f"unsupported file type {path.suffix}")
        parser, _kind = found
        small = path.stat().st_size <= getattr(parser, "inprocess_max_bytes", -1)
        if parser.sandboxed and not small:
            self.queue.progress(job.id, 0.1, "parsing")
            return run_sandboxed(parser.name, path, self.settings.parse_timeout_s, self.settings.parse_memory_mb)
        return parser.parse(path, ParseContext(
            transcriber=self.transcriber, vocabulary_prompt=self.vocabulary(),
            extra={"progress": lambda f, m: self.queue.progress(job.id, f * 0.95, m),
                   "timeout_s": max(self.settings.parse_timeout_s, 1800),
                   "memory_mb": max(self.settings.parse_memory_mb, 4096)},
        ))

    def _has_chunks(self, source_id: str) -> bool:
        return self.index.reader().execute(
            "SELECT 1 FROM chunks WHERE source_id = ? LIMIT 1", (source_id,)).fetchone() is not None

    def _drop_chunks(self, source_id: str) -> None:
        with self.index.write() as conn:
            rowids = [r[0] for r in conn.execute("SELECT rowid FROM chunks WHERE source_id = ?", (source_id,))]
            self.vectors.remove(conn, rowids)
            conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))

    def _store_chunks(self, src: Source, drafts) -> None:  # type: ignore[no-untyped-def]
        conn = self.index.reader()
        old = conn.execute("SELECT rowid, content_hash FROM chunks WHERE source_id = ?", (src.id,)).fetchall()
        reuse = self._existing_vectors([r[0] for r in old], [r[1] for r in old])
        need = [d for d in drafts if d.content_hash not in reuse]
        fresh = self.embedder.embed([d.text for d in need]) if need else np.zeros((0, 0))
        new_vecs = {d.content_hash: fresh[i] for i, d in enumerate(need)}
        now = utcnow()
        with self.index.write() as wconn:
            self.vectors.remove(wconn, [r[0] for r in old])
            wconn.execute("DELETE FROM chunks WHERE source_id = ?", (src.id,))
            for i, d in enumerate(drafts):
                cur = wconn.execute(
                    "INSERT INTO chunks(id, source_id, ord, text, locator, content_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (new_id("chunk"), src.id, i, d.text, dumps(d.locator), d.content_hash, now),
                )
                vec = reuse.get(d.content_hash)
                self.vectors.add(wconn, cur.lastrowid, vec if vec is not None else new_vecs[d.content_hash])  # type: ignore[arg-type]

    def _existing_vectors(self, rowids: list[int], hashes: list[str]) -> dict[str, np.ndarray]:
        if not rowids:
            return {}
        conn = self.index.reader()
        # One JSON parameter, not one "?" per chunk: a long transcript can have more chunks than
        # SQLite's host-parameter limit (999 on older builds).
        ids = json.dumps(rowids)
        if self.index.has_vec:
            rows = conn.execute("SELECT rowid, embedding FROM chunk_vec WHERE rowid IN (SELECT value FROM json_each(?))", (ids,))
        else:
            rows = conn.execute("SELECT chunk_rowid, vec FROM chunk_vectors WHERE chunk_rowid IN (SELECT value FROM json_each(?))", (ids,))
        by_rowid = {r[0]: np.frombuffer(r[1], dtype=np.float32).copy() for r in rows}
        return {h: by_rowid[rid] for rid, h in zip(rowids, hashes, strict=True) if rid in by_rowid}

    # --- forget ---------------------------------------------------------------------------

    def forget_source(self, source_id: str) -> dict[str, int]:
        with self.kdb._write_lock:
            return self._forget_source(source_id)

    def _forget_source(self, source_id: str) -> dict[str, int]:
        """"Forget this file": drop its chunks, embeddings and unverified claims. Verified claims
        that rested only on it are kept but flagged for review (proposal: "Right to forget")."""
        if repo.get_source(self.kdb, source_id) is None:
            raise NotFound(f"source {source_id} not found")
        stats = {"claims_removed": 0, "claims_flagged": 0, "evidence_removed": 0}
        with self.ledger.group("user", "source.forget", source_id) as tx:
            for c in tx.find("claims", {"evidence.source_id": source_id}):
                kept = [e for e in c["evidence"] if e.get("source_id") != source_id]
                stats["evidence_removed"] += len(c["evidence"]) - len(kept)
                if kept:
                    tx.update("claims", c["id"], {"evidence": kept})
                elif c["status"] == ClaimStatus.VERIFIED:
                    tx.update("claims", c["id"], {"evidence": kept, "needs_review": True})
                    stats["claims_flagged"] += 1
                else:
                    tx.delete("claims", c["id"])
                    stats["claims_removed"] += 1
        self._drop_chunks(source_id)
        repo.set_source_status(self.kdb, source_id, SourceStatus.FORGOTTEN, indexed_hash=None)
        self._changed(source_id)
        return stats

    # --- serving originals (read-only) ----------------------------------------------------

    def source_path(self, source_id: str) -> Path:
        src = repo.get_source(self.kdb, source_id)
        if src is None or src.status == SourceStatus.FORGOTTEN:
            raise NotFound(f"source {source_id} not found")
        path = Path(src.path)
        if not path.is_file():
            raise NotFound(f"{path} is missing")
        return path
