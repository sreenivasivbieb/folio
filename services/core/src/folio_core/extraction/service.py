"""Job handler ``extract_source``: chunks -> candidates -> resolved, schema-valid *proposed* claims.

* Each chunk's output is cached by (chunk hash, model, prompt version, schema version): re-running
  on unchanged data makes zero model calls (NFR: cost).
* Claims are written as ``proposed`` through KnowledgeService, which refuses anything the user
  already rejected and never touches verified claims (FR-7, FR-8).
* After a re-extraction, proposals from this source that were not produced again are pruned.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ..domain.errors import InvalidInput
from ..domain.ids import new_id
from ..domain.models import ClaimStatus, EntityStatus, Extractor, Source, SourceStatus
from ..domain.schema import REPRESENTED_BY
from ..jobs import Job, JobQueue
from ..knowledge import KnowledgeService
from ..learning import CorrectionStore
from ..ledger import Ledger, Tx
from ..providers.privacy import ensure_allowed
from ..store import repo
from ..store.db import Database, dumps, utcnow
from .resolver import EntityResolver
from .rules import DOCUMENT_REF
from .types import ExtractionContext, ExtractionFailed, ExtractionOutput
from .types import Extractor as ExtractorProto
from .validate import validate_output

log = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, *, db: Database, ledger: Ledger, knowledge: KnowledgeService,
                 learning: CorrectionStore, resolver: EntityResolver, extractor: ExtractorProto,
                 queue: JobQueue) -> None:
        self.db = db
        self.ledger = ledger
        self.knowledge = knowledge
        self.learning = learning
        self.resolver = resolver
        self.extractor = extractor
        self.queue = queue

    def cache_key(self, chunk_hash: str, schema_version: int) -> str:
        raw = f"{chunk_hash}|{self.extractor.model_id}|{self.extractor.prompt_version}|{schema_version}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def extract_source(self, job: Job) -> str:
        src = repo.get_source(self.db.reader(), job.payload["source_id"])
        if src is None or src.status != SourceStatus.INDEXED:
            return "skipped: source not indexed"
        if self.extractor.uses_llm:
            ensure_allowed(self.db, getattr(self.extractor, "llm", None))
        chunks = repo.chunks_for_source(self.db.reader(), src.id)
        version, schema = self.knowledge.schema()
        gazetteer = self.learning.gazetteer(include_rejected=True)
        doc_name = Path(src.path).name
        actor = f"model:{self.extractor.model_id}"
        extractor_meta = Extractor(kind="model", model=self.extractor.model_id,
                                   prompt_version=self.extractor.prompt_version)
        produced: set[str] = set()
        stats = {"created": 0, "merged": 0, "blocked": 0, "cached": 0, "failed": 0}

        for i, chunk in enumerate(chunks):
            key = self.cache_key(chunk.content_hash, version)
            cached = repo.cache_get(self.db.reader(), key)
            if cached is not None:
                out = ExtractionOutput.model_validate(cached)
                stats["cached"] += 1
            else:
                ctx = ExtractionContext(
                    schema=schema, gazetteer=gazetteer, document_name=doc_name,
                    few_shot=self.learning.few_shot(chunk.text) if self.extractor.uses_llm else [],
                    negatives=self.learning.negatives(chunk.text) if self.extractor.uses_llm else [],
                )
                try:
                    out, _problems = validate_output(self.extractor.extract(chunk.text, ctx), schema, chunk.text)
                except ExtractionFailed as exc:
                    self._record_issue(src.id, chunk.id, str(exc), exc.raw)
                    stats["failed"] += 1
                    continue
                with self.db.write() as conn:
                    repo.cache_put(conn, key, "extract", self.extractor.model_id, out.model_dump())

            created_entities = False
            with self.ledger.group(actor, "extract", doc_name) as tx:
                doc_entity: str | None = None
                for c in out.claims:
                    if c.subject == DOCUMENT_REF:
                        doc_entity = doc_entity or self._document_entity(tx, src)
                        subject_id: str | None = doc_entity
                    else:
                        subject_id = self.resolver.resolve(tx, c.subject, c.subject_type, actor)
                    object_id = (self.resolver.resolve(tx, c.object, c.object_type, actor)
                                 if c.object and c.object_type else None)
                    if subject_id is None or (c.object and object_id is None):
                        stats["blocked"] += 1
                        continue
                    try:
                        claim_id, outcome = self.knowledge.add_claim_tx(
                            tx, subject_id=subject_id, predicate=c.predicate, value=c.value,
                            object_id=object_id, valid_from=c.valid_from,
                            confidence=c.confidence, status=ClaimStatus.PROPOSED,
                            extractor=extractor_meta, schema=(version, schema),
                            evidence=[{"source_id": src.id, "chunk_id": chunk.id,
                                       "locator": chunk.locator.model_dump(exclude_none=True),
                                       "quote": c.quote}],
                        )
                    except InvalidInput as exc:
                        log.debug("dropping invalid claim %s: %s", c, exc)
                        continue
                    stats[outcome] += 1
                    if claim_id:
                        produced.add(claim_id)
                created_entities = any(t == "entities" for t, _ in tx.changed)
            if created_entities:
                gazetteer = self.learning.gazetteer(include_rejected=True)
            self.queue.progress(job.id, (i + 1) / max(len(chunks), 1), f"chunk {i + 1}/{len(chunks)}")

        pruned = self._prune(src, {c.id for c in chunks}, produced, actor)
        return (f"{stats['created']} new, {stats['merged']} reinforced, {stats['blocked']} blocked by "
                f"corrections, {pruned} stale removed, {stats['cached']} cached, {stats['failed']} failed")

    def _document_entity(self, tx: Tx, src: Source) -> str:
        """The entity that *is* this file: one the user labeled ("This PDF is the Acme contract")
        or an auto-created Document entity."""
        r = tx.conn.execute(
            "SELECT subject_id FROM claims WHERE predicate = ? AND value = ? AND status != 'rejected' "
            "ORDER BY status = 'verified' DESC LIMIT 1",
            (REPRESENTED_BY, dumps(src.id)),
        ).fetchone()
        if r:
            return repo.resolve_merged(tx.conn, r[0])
        entity = self.knowledge.create_entity_tx(tx, "Document", Path(src.path).name,
                                                 actor="system", status=EntityStatus.AUTO)
        self.knowledge.add_claim_tx(tx, subject_id=entity["id"], predicate=REPRESENTED_BY,
                                    value=src.id, status=ClaimStatus.VERIFIED,
                                    extractor=Extractor(kind="system"))
        return entity["id"]

    def _prune(self, src: Source, live_chunks: set[str], produced: set[str], actor: str) -> int:
        conn = self.db.reader()
        rows = conn.execute(
            "SELECT ev.id, ev.claim_id, ev.chunk_id FROM evidence ev JOIN claims c ON c.id = ev.claim_id "
            "WHERE ev.source_id = ? AND c.status = 'proposed' "
            "AND json_extract(c.extractor, '$.kind') = 'model'", (src.id,),
        ).fetchall()
        stale = [r for r in rows if r["claim_id"] not in produced or r["chunk_id"] not in live_chunks]
        if not stale:
            return 0
        removed = 0
        with self.ledger.group(actor, "extract.prune", Path(src.path).name) as tx:
            for r in stale:
                tx.delete("evidence", r["id"])
            for claim_id in {r["claim_id"] for r in stale}:
                left = tx.conn.execute("SELECT COUNT(*) FROM evidence WHERE claim_id = ?", (claim_id,)).fetchone()[0]
                if not left:
                    tx.delete("claims", claim_id)
                    removed += 1
            # Auto entities left with no claims at all are noise: remove them.
            for e in tx.conn.execute(
                "SELECT id FROM entities e WHERE status = 'auto' AND created_by = ? AND NOT EXISTS "
                "(SELECT 1 FROM claims c WHERE c.subject_id = e.id OR c.object_id = e.id)", (actor,),
            ).fetchall():
                for a in tx.conn.execute("SELECT id FROM aliases WHERE entity_id = ?", (e["id"],)).fetchall():
                    tx.delete("aliases", a["id"])
                tx.delete("entities", e["id"])
        return removed

    def _record_issue(self, source_id: str, chunk_id: str, reason: str, raw: str | None) -> None:
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO ix.extraction_issues(id, source_id, chunk_id, reason, raw, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("job"), source_id, chunk_id, reason, (raw or "")[:4000], utcnow()),
            )
