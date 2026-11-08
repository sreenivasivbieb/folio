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

import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..config import Settings
from ..domain.errors import InvalidInput, NotFound
from ..domain.ids import new_id
from ..domain.models import ClaimStatus, Root, Source, SourceKind, SourceStatus
from ..jobs import Job, JobQueue
from ..ledger import Ledger
from ..providers.embeddings.base import Embedder
from ..providers.stt.base import Transcriber
from ..realtime import Bus
from ..store import repo
from ..store.index_db import IndexDB, dumps, utcnow
from ..store.mongo import KnowledgeDB
from ..store.vectors import VectorIndex
from .base import ParseContext
from .chunker import chunk_units
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

    def add_root(self, path: str, watch: bool = True) -> Root:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise InvalidInput(f"{p} does not exist")
        if p.is_file() and not self.registry.supports(p):
            raise InvalidInput(f"unsupported file type: {p.suffix or p.name}")
        existing = self.kdb["roots"].find_one({"path": str(p)})
        if existing:
            root = repo.root_from_doc(existing)
        else:
            with self.ledger.group("user", "root.add", str(p)) as tx:
                row = tx.insert("roots", {
                    "id": new_id("root"), "path": str(p), "kind": "file" if p.is_file() else "folder",
                    "watch": watch, "created_at": utcnow(),
                })
            root = Root(**row)
        self.scan_root(root)
        return root

    def remove_root(self, root_id: str) -> int:
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

    def _iter_files(self, root: Root) -> list[Path]:
        base = Path(root.path)
        if root.kind == "file":
            return [base] if base.exists() else []
        files: list[Path] = []
        data_dir = self.settings.data_dir.resolve()
        for dirpath, dirnames, filenames in os.walk(base):
            d = Path(dirpath)
            dirnames[:] = [n for n in dirnames if not n.startswith(".") and (d / n).resolve() != data_dir]
            files += [d / n for n in filenames if not n.startswith(".") and self.registry.supports(d / n)]
        return files

    def scan_root(self, root: Root) -> int:
        priority = PRIORITY_SELECTED_FILE if root.kind == "file" else PRIORITY_FOLDER_SCAN
        seen: set[str] = set()
        queued = 0
        for f in self._iter_files(root):
            seen.add(str(f))
            queued += self._track(f, root.id, priority)
        # Files that disappeared from a folder root are marked missing (their knowledge stays).
        for d in self.kdb["sources"].find({"root_id": root.id, "status": {"$nin": ["missing", "forgotten", "removed"]}}):
            if d["path"] not in seen and not Path(d["path"]).exists():
                repo.set_source_status(self.kdb, d["_id"], SourceStatus.MISSING)
                self._changed(d["_id"])
        return queued

    def _root_for(self, path: Path) -> Root | None:
        for root in self.roots():
            rp = Path(root.path)
            if path == rp or rp in path.parents:
                return root
        return None

    def scan_path(self, path: Path) -> None:
        """Called by the folder watcher for one changed path."""
        path = path.resolve()
        root = self._root_for(path)
        if root is None:
            return
        if path.is_file() and self.registry.supports(path):
            self._track(path, root.id, PRIORITY_WATCH_CHANGE)
        elif not path.exists():
            src = repo.source_by_path(self.kdb, str(path))
            if src and src.status not in (SourceStatus.FORGOTTEN, SourceStatus.REMOVED):
                repo.set_source_status(self.kdb, src.id, SourceStatus.MISSING)
                self._changed(src.id)

    def rescan_all(self) -> int:
        return sum(self.scan_root(r) for r in self.roots())

    def _track(self, path: Path, root_id: str, priority: int) -> int:
        """Upsert the source; queue indexing if the file is new or its size/mtime changed."""
        found = self.registry.for_path(path)
        if found is None:
            return 0
        _parser, kind = found
        st = path.stat()
        now = utcnow()
        src = repo.source_by_path(self.kdb, str(path))
        if src is None:
            src_id = new_id("source")
            self.kdb["sources"].insert_one({
                "_id": src_id, "root_id": root_id, "path": str(path), "kind": kind.value,
                "size": st.st_size, "mtime": st.st_mtime, "content_hash": None, "indexed_hash": None,
                "status": SourceStatus.PENDING.value, "error": None, "priority": priority,
                "created_at": now, "updated_at": now,
            })
        else:
            src_id = src.id
            if src.status == SourceStatus.FORGOTTEN:
                return 0  # the user asked us to forget this file
            if (src.size == st.st_size and src.mtime == st.st_mtime and src.status == SourceStatus.INDEXED):
                return 0
            self.kdb["sources"].update_one({"_id": src_id}, {
                "$set": {"root_id": root_id, "status": SourceStatus.PENDING.value, "error": None, "updated_at": now},
                "$max": {"priority": priority},
            })
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
        src = repo.get_source(self.kdb, job.payload["source_id"])
        if src is None or src.status in (SourceStatus.FORGOTTEN, SourceStatus.REMOVED):
            return "skipped: source no longer tracked"
        path = Path(src.path)
        if not path.exists():
            repo.set_source_status(self.kdb, src.id, SourceStatus.MISSING)
            self._changed(src.id)
            return "file missing"
        repo.set_source_status(self.kdb, src.id, SourceStatus.INDEXING)
        self._changed(src.id)
        st = path.stat()
        self.queue.progress(job.id, 0.01, "hashing")
        digest = file_hash(path)
        if digest == src.indexed_hash and self._has_chunks(src.id):
            repo.set_source_status(self.kdb, src.id, SourceStatus.INDEXED, size=st.st_size,
                                   mtime=st.st_mtime, content_hash=digest)
            self._changed(src.id)
            return "unchanged (content hash match): nothing to do"
        try:
            units = self._parse(path, job)
            drafts = chunk_units(units)
            self.queue.progress(job.id, 0.96, f"{len(drafts)} chunks; embedding")
            self._store_chunks(src, drafts)
        except Exception as exc:
            repo.set_source_status(self.kdb, src.id, SourceStatus.FAILED, error=str(exc)[:1000])
            self._changed(src.id)
            raise
        repo.set_source_status(self.kdb, src.id, SourceStatus.INDEXED, size=st.st_size,
                               mtime=st.st_mtime, content_hash=digest, indexed_hash=digest)
        self._changed(src.id)
        priority = (self.kdb["sources"].find_one({"_id": src.id}, {"priority": 1}) or {}).get("priority", 0)
        self.queue.enqueue("extract_source", {"source_id": src.id}, dedupe_key=f"extract:{src.id}", priority=priority)
        return f"indexed {len(drafts)} chunks"

    def _parse(self, path: Path, job: Job):  # type: ignore[no-untyped-def]
        found = self.registry.for_path(path)
        if found is None:
            raise InvalidInput(f"unsupported file type {path.suffix}")
        parser, _kind = found
        if parser.sandboxed:
            self.queue.progress(job.id, 0.1, "parsing")
            return run_sandboxed(parser.name, path, self.settings.parse_timeout_s, self.settings.parse_memory_mb)
        return parser.parse(path, ParseContext(
            transcriber=self.transcriber, vocabulary_prompt=self.vocabulary(),
            extra={"progress": lambda f, m: self.queue.progress(job.id, f * 0.95, m)},
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
        marks = ",".join("?" * len(rowids))
        if self.index.has_vec:
            rows = conn.execute(f"SELECT rowid, embedding FROM chunk_vec WHERE rowid IN ({marks})", rowids)
        else:
            rows = conn.execute(f"SELECT chunk_rowid, vec FROM chunk_vectors WHERE chunk_rowid IN ({marks})", rowids)
        by_rowid = {r[0]: np.frombuffer(r[1], dtype=np.float32).copy() for r in rows}
        return {h: by_rowid[rid] for rid, h in zip(rowids, hashes, strict=True) if rid in by_rowid}

    # --- forget ---------------------------------------------------------------------------

    def forget_source(self, source_id: str) -> dict[str, int]:
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
