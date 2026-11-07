"""Ingestion orchestration: selected roots -> sources -> chunks (+ FTS + vectors).

Flow for one file (FR-1, FR-2):

    scan -> source row (path, size, mtime) -> job "index_source"
         -> content hash unchanged?  -> stop (zero parser and model calls)
         -> parse (sandboxed) -> chunk -> embed (reusing vectors of unchanged chunks)
         -> replace the source's chunks in index.db -> job "extract_source"

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
from ..domain.models import Root, Source, SourceStatus
from ..jobs import Job, JobQueue
from ..ledger import Ledger
from ..providers.embeddings.base import Embedder
from ..providers.stt.base import Transcriber
from ..realtime import Bus
from ..store import repo
from ..store.db import Database, dumps, utcnow
from ..store.vectors import VectorIndex
from .base import ParseContext
from .chunker import chunk_units
from .registry import ParserRegistry
from .sandbox import run_sandboxed

log = logging.getLogger(__name__)

PRIORITY_SELECTED_FILE = 10  # "selected files first" (risk: slow indexing of long videos)
PRIORITY_WATCH_CHANGE = 5
PRIORITY_FOLDER_SCAN = 0


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class IngestionService:
    def __init__(self, *, db: Database, ledger: Ledger, queue: JobQueue, bus: Bus,
                 registry: ParserRegistry, embedder: Embedder, vectors: VectorIndex,
                 transcriber: Transcriber, settings: Settings,
                 vocabulary: Callable[[], str | None] = lambda: None) -> None:
        self.db = db
        self.ledger = ledger
        self.queue = queue
        self.bus = bus
        self.registry = registry
        self.embedder = embedder
        self.vectors = vectors
        self.transcriber = transcriber
        self.settings = settings
        self.vocabulary = vocabulary

    # --- roots ----------------------------------------------------------------------------

    def add_root(self, path: str, watch: bool = True) -> Root:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise InvalidInput(f"{p} does not exist")
        if p.is_file() and not self.registry.supports(p):
            raise InvalidInput(f"unsupported file type: {p.suffix or p.name}")
        existing = self.db.reader().execute("SELECT * FROM roots WHERE path = ?", (str(p),)).fetchone()
        if existing:
            root = repo.root_from_row(existing)
        else:
            with self.ledger.group("user", "root.add", str(p)) as tx:
                row = tx.insert("roots", {
                    "id": new_id("root"), "path": str(p), "kind": "file" if p.is_file() else "folder",
                    "watch": int(watch), "created_at": utcnow(),
                })
            root = repo.root_from_row(row)  # type: ignore[arg-type]
        self.scan_root(root)
        return root

    def remove_root(self, root_id: str) -> None:
        with self.ledger.group("user", "root.remove") as tx:
            if tx.delete("roots", root_id) is None:
                raise NotFound(f"root {root_id} not found")

    def roots(self) -> list[Root]:
        return repo.list_roots(self.db.reader())

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
        with self.db.write() as conn:
            for r in conn.execute("SELECT id, path FROM sources WHERE root_id = ? AND status NOT IN ('missing', 'forgotten')", (root.id,)).fetchall():
                if r["path"] not in seen and not Path(r["path"]).exists():
                    repo.set_source_status(conn, r["id"], SourceStatus.MISSING)
        return queued

    def scan_path(self, path: Path) -> None:
        """Called by the folder watcher for one changed path."""
        path = path.resolve()
        for root in self.roots():
            rp = Path(root.path)
            if path == rp or rp in path.parents:
                if path.exists() and path.is_file() and self.registry.supports(path):
                    self._track(path, root.id, PRIORITY_WATCH_CHANGE)
                elif not path.exists():
                    with self.db.write() as conn:
                        src = repo.source_by_path(conn, str(path))
                        if src and src.status != SourceStatus.FORGOTTEN:
                            repo.set_source_status(conn, src.id, SourceStatus.MISSING)
                return

    def rescan_all(self) -> int:
        return sum(self.scan_root(r) for r in self.roots())

    def _track(self, path: Path, root_id: str, priority: int) -> int:
        """Upsert the source row; queue indexing if the file is new or its size/mtime changed."""
        found = self.registry.for_path(path)
        if found is None:
            return 0
        _parser, kind = found
        st = path.stat()
        now = utcnow()
        with self.db.write() as conn:
            src = repo.source_by_path(conn, str(path))
            if src is None:
                src_id = new_id("source")
                conn.execute(
                    "INSERT INTO sources(id, root_id, path, kind, size, mtime, status, priority, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                    (src_id, root_id, str(path), kind.value, st.st_size, st.st_mtime, priority, now, now),
                )
            else:
                src_id = src.id
                if src.status == SourceStatus.FORGOTTEN:
                    return 0  # the user asked us to forget this file
                unchanged = (src.size == st.st_size and src.mtime == st.st_mtime
                             and src.status == SourceStatus.INDEXED)
                if unchanged:
                    return 0
                conn.execute("UPDATE sources SET root_id = COALESCE(root_id, ?), status = 'pending', "
                             "priority = MAX(priority, ?), updated_at = ? WHERE id = ?",
                             (root_id, priority, now, src_id))
        self.bus.publish({"type": "source", "source_id": src_id})
        job = self.queue.enqueue("index_source", {"source_id": src_id},
                                 dedupe_key=f"index:{src_id}", priority=priority)
        return 1 if job else 0

    # --- indexing (job handler) -----------------------------------------------------------

    def index_source(self, job: Job) -> str:
        source_id = job.payload["source_id"]
        src = repo.get_source(self.db.reader(), source_id)
        if src is None or src.status == SourceStatus.FORGOTTEN:
            return "skipped: source no longer tracked"
        path = Path(src.path)
        if not path.exists():
            with self.db.write() as conn:
                repo.set_source_status(conn, src.id, SourceStatus.MISSING)
            return "file missing"
        st = path.stat()
        digest = file_hash(path)
        if digest == src.indexed_hash and self._has_chunks(src.id):
            with self.db.write() as conn:
                repo.set_source_status(conn, src.id, SourceStatus.INDEXED, size=st.st_size,
                                       mtime=st.st_mtime, content_hash=digest)
            self.bus.publish({"type": "source", "source_id": src.id})
            return "unchanged (content hash match): nothing to do"

        with self.db.write() as conn:
            repo.set_source_status(conn, src.id, SourceStatus.INDEXING)
        self.bus.publish({"type": "source", "source_id": src.id})
        try:
            units = self._parse(path)
            drafts = chunk_units(units)
            self.queue.progress(job.id, 0.5, f"{len(drafts)} chunks; embedding")
            self._store_chunks(src, drafts)
        except Exception as exc:
            with self.db.write() as conn:
                repo.set_source_status(conn, src.id, SourceStatus.FAILED, error=str(exc)[:1000])
            self.bus.publish({"type": "source", "source_id": src.id})
            raise
        with self.db.write() as conn:
            repo.set_source_status(conn, src.id, SourceStatus.INDEXED, size=st.st_size,
                                   mtime=st.st_mtime, content_hash=digest, indexed_hash=digest)
        self.bus.publish({"type": "source", "source_id": src.id})
        priority = self.db.reader().execute(
            "SELECT priority FROM sources WHERE id = ?", (src.id,)).fetchone()[0]
        self.queue.enqueue("extract_source", {"source_id": src.id},
                           dedupe_key=f"extract:{src.id}", priority=priority)
        return f"indexed {len(drafts)} chunks"

    def _parse(self, path: Path):  # type: ignore[no-untyped-def]
        found = self.registry.for_path(path)
        if found is None:
            raise InvalidInput(f"unsupported file type {path.suffix}")
        parser, _kind = found
        if parser.sandboxed:
            return run_sandboxed(parser.name, path, self.settings.parse_timeout_s,
                                 self.settings.parse_memory_mb)
        return parser.parse(path, ParseContext(transcriber=self.transcriber,
                                               vocabulary_prompt=self.vocabulary()))

    def _has_chunks(self, source_id: str) -> bool:
        return self.db.reader().execute(
            "SELECT 1 FROM ix.chunks WHERE source_id = ? LIMIT 1", (source_id,)
        ).fetchone() is not None

    def _store_chunks(self, src: Source, drafts) -> None:  # type: ignore[no-untyped-def]
        conn = self.db.reader()
        old = conn.execute("SELECT rowid, content_hash FROM ix.chunks WHERE source_id = ?",
                           (src.id,)).fetchall()
        reuse = self._existing_vectors([r[0] for r in old], [r[1] for r in old])
        need = [d for d in drafts if d.content_hash not in reuse]
        fresh = self.embedder.embed([d.text for d in need]) if need else np.zeros((0, 0))
        new_vecs = {d.content_hash: fresh[i] for i, d in enumerate(need)}
        now = utcnow()
        with self.db.write() as wconn:
            self.vectors.remove(wconn, [r[0] for r in old])
            wconn.execute("DELETE FROM ix.chunks WHERE source_id = ?", (src.id,))
            for i, d in enumerate(drafts):
                cur = wconn.execute(
                    "INSERT INTO ix.chunks(id, source_id, ord, text, locator, content_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (new_id("chunk"), src.id, i, d.text, dumps(d.locator), d.content_hash, now),
                )
                vec = reuse.get(d.content_hash)
                self.vectors.add(wconn, cur.lastrowid, vec if vec is not None else new_vecs[d.content_hash])  # type: ignore[arg-type]

    def _existing_vectors(self, rowids: list[int], hashes: list[str]) -> dict[str, np.ndarray]:
        if not rowids:
            return {}
        conn = self.db.reader()
        marks = ",".join("?" * len(rowids))
        if self.db.has_vec:
            rows = conn.execute(f"SELECT rowid, embedding FROM ix.chunk_vec WHERE rowid IN ({marks})", rowids)
        else:
            rows = conn.execute(f"SELECT chunk_rowid, vec FROM ix.chunk_vectors WHERE chunk_rowid IN ({marks})", rowids)
        by_rowid = {r[0]: np.frombuffer(r[1], dtype=np.float32).copy() for r in rows}
        return {h: by_rowid[rid] for rid, h in zip(rowids, hashes, strict=True) if rid in by_rowid}

    # --- forget ---------------------------------------------------------------------------

    def forget_source(self, source_id: str) -> dict[str, int]:
        """"Forget this file": drop its chunks, embeddings and unverified claims. Verified claims
        that rested only on it are kept but flagged for review (proposal: "Right to forget")."""
        conn = self.db.reader()
        if repo.get_source(conn, source_id) is None:
            raise NotFound(f"source {source_id} not found")
        stats = {"claims_removed": 0, "claims_flagged": 0, "evidence_removed": 0}
        ev_rows = conn.execute("SELECT id, claim_id FROM evidence WHERE source_id = ?", (source_id,)).fetchall()
        with self.ledger.group("user", "source.forget", source_id) as tx:
            for ev in ev_rows:
                tx.delete("evidence", ev["id"])
                stats["evidence_removed"] += 1
            for claim_id in {ev["claim_id"] for ev in ev_rows}:
                claim = tx.conn.execute("SELECT status FROM claims WHERE id = ?", (claim_id,)).fetchone()
                left = tx.conn.execute("SELECT COUNT(*) FROM evidence WHERE claim_id = ?", (claim_id,)).fetchone()[0]
                if claim is None or left:
                    continue
                if claim["status"] == "verified":
                    tx.update("claims", claim_id, {"needs_review": 1})
                    stats["claims_flagged"] += 1
                else:
                    tx.delete("claims", claim_id)
                    stats["claims_removed"] += 1
        with self.db.write() as wconn:
            rowids = [r[0] for r in wconn.execute("SELECT rowid FROM ix.chunks WHERE source_id = ?", (source_id,))]
            self.vectors.remove(wconn, rowids)
            wconn.execute("DELETE FROM ix.chunks WHERE source_id = ?", (source_id,))
            repo.set_source_status(wconn, source_id, SourceStatus.FORGOTTEN, indexed_hash=None)
        self.bus.publish({"type": "source", "source_id": source_id})
        return stats

    # --- serving originals (read-only) ----------------------------------------------------

    def source_path(self, source_id: str) -> Path:
        src = repo.get_source(self.db.reader(), source_id)
        if src is None or src.status == SourceStatus.FORGOTTEN:
            raise NotFound(f"source {source_id} not found")
        path = Path(src.path)
        if not path.is_file():
            raise NotFound(f"{path} is missing")
        return path

