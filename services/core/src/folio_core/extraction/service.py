"""Job handler ``extract_source``: chunks -> candidates -> resolved *proposed* claims.

* The extractor is chosen per job: the project's LLM when one is configured (bring your own
  key), otherwise the offline rule extractor.
* Each chunk's output is cached by (chunk hash, extractor, prompt version, hints version):
  re-running on unchanged data makes zero model calls (NFR: cost).
* Claims are written as ``proposed`` through KnowledgeService, which refuses anything the user
  already rejected and never touches verified claims (FR-7, FR-8).
* After a re-extraction, proposals from this source that were not produced again are pruned.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
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
from ..store.index_db import IndexDB, utcnow
from ..store.mongo import KnowledgeDB
from .resolver import EntityResolver
from .rules import DOCUMENT_REF
from .types import ExtractionContext, ExtractionFailed, ExtractionOutput
from .types import Extractor as ExtractorProto
from .validate import validate_output

log = logging.getLogger(__name__)


class ExtractionService:
    def __init__(self, *, kdb: KnowledgeDB, index: IndexDB, ledger: Ledger, knowledge: KnowledgeService,
                 learning: CorrectionStore, resolver: EntityResolver,
                 extractor: Callable[[], ExtractorProto], queue: JobQueue) -> None:
        self.kdb = kdb
        self.index = index
        self.ledger = ledger
        self.knowledge = knowledge
        self.learning = learning
        self.resolver = resolver
        self.extractor = extractor
        self.queue = queue

    @staticmethod
    def cache_key(extractor: ExtractorProto, chunk_hash: str, schema_version: int) -> str:
        raw = f"{chunk_hash}|{extractor.model_id}|{extractor.prompt_version}|{schema_version}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def enqueue_all(self) -> int:
        """Re-extract every indexed file (e.g. after choosing an LLM). Cached chunks are free."""
        n = 0
        for d in self.kdb["sources"].find({"status": SourceStatus.INDEXED.value}, {"_id": 1, "priority": 1}):
            if self.queue.enqueue("extract_source", {"source_id": d["_id"]}, dedupe_key=f"extract:{d['_id']}",
                                  priority=d.get("priority", 0)):
                n += 1
        return n

    def extract_source(self, job: Job) -> str:
        src = repo.get_source(self.kdb, job.payload["source_id"])
        if src is None or src.status != SourceStatus.INDEXED:
            return "skipped: source not indexed"
        extractor = self.extractor()
        if extractor.uses_llm:
            ensure_allowed(self.kdb, getattr(extractor, "llm", None))
        chunks = repo.chunks_for_source(self.index.reader(), src.id)
        version, schema = self.knowledge.schema()
        gazetteer = self.learning.gazetteer(include_rejected=True)
        known_types = self.knowledge.known_types()
        doc_name = Path(src.path).name
        actor = f"model:{extractor.model_id}"
        meta = Extractor(kind="model", model=extractor.model_id, prompt_version=extractor.prompt_version)
        produced: set[str] = set()
        stats = {"created": 0, "merged": 0, "blocked": 0, "cached": 0, "failed": 0}

        for i, chunk in enumerate(chunks):
            self.queue.progress(job.id, i / max(len(chunks), 1), f"{extractor.model_id}: chunk {i + 1}/{len(chunks)}")
            key = self.cache_key(extractor, chunk.content_hash, version)
            cached = repo.cache_get(self.index.reader(), key)
            if cached is not None:
                out = ExtractionOutput.model_validate(cached)
                stats["cached"] += 1
            else:
                ctx = ExtractionContext(
                    schema=schema, gazetteer=gazetteer, document_name=doc_name,
                    few_shot=self.learning.few_shot(chunk.text) if extractor.uses_llm else [],
                    negatives=self.learning.negatives(chunk.text) if extractor.uses_llm else [],
                )
                try:
                    out, _problems = validate_output(extractor.extract(chunk.text, ctx), schema, chunk.text)
                except ExtractionFailed as exc:
                    self._record_issue(src.id, chunk.id, str(exc), exc.raw)
                    stats["failed"] += 1
                    continue
                with self.index.write() as conn:
                    repo.cache_put(conn, key, "extract", extractor.model_id, out.model_dump())

            if not out.claims:
                continue
            with self.ledger.group(actor, "extract", doc_name) as tx:
                doc_entity: str | None = None
                for c in out.claims:
                    if c.subject == DOCUMENT_REF:
                        doc_entity = doc_entity or self._document_entity(tx, src)
                        subject_id: str | None = doc_entity
                    else:
                        subject_id = self.resolver.resolve(tx, c.subject, c.subject_type, actor, known_types)
                    object_id = (self.resolver.resolve(tx, c.object, c.object_type, actor, known_types)
                                 if c.object and c.object_type else None)
                    if subject_id is None or (c.object and object_id is None):
                        stats["blocked"] += 1
                        continue
                    try:
                        claim_id, outcome = self.knowledge.add_claim_tx(
                            tx, subject_id=subject_id, predicate=c.predicate, value=c.value,
                            object_id=object_id, valid_from=c.valid_from, confidence=c.confidence,
                            status=ClaimStatus.PROPOSED, extractor=meta, schema=(version, schema),
                            evidence=[{"source_id": src.id, "chunk_id": chunk.id,
                                       "locator": chunk.locator.model_dump(exclude_none=True), "quote": c.quote}],
                        )
                    except InvalidInput as exc:
                        log.debug("dropping invalid claim %s: %s", c, exc)
                        continue
                    stats[outcome] += 1
                    if claim_id:
                        produced.add(claim_id)
                new_entities = any(coll == "entities" for coll, _ in tx.changed)
            if new_entities:  # later chunks should know the names found so far
                gazetteer = self.learning.gazetteer(include_rejected=True)

        pruned = self._prune(src, {c.id for c in chunks}, produced, actor)
        return (f"{extractor.model_id}: {stats['created']} new, {stats['merged']} reinforced, "
                f"{stats['blocked']} blocked by corrections, {pruned} stale removed, "
                f"{stats['cached']} cached, {stats['failed']} failed")

    def _document_entity(self, tx: Tx, src: Source) -> str:
        """The entity that *is* this file: one the user labeled ("This PDF is the Acme contract")
        or an auto-created Document entity."""
        rows = tx.find("claims", {"predicate": REPRESENTED_BY, "value": src.id, "status": {"$ne": "rejected"}})
        if rows:
            rows.sort(key=lambda r: r["status"] != "verified")
            return repo.resolve_merged(self.kdb, rows[0]["subject_id"], tx.session)
        entity = self.knowledge.create_entity_tx(tx, "Document", Path(src.path).name, actor="system",
                                                 status=EntityStatus.AUTO)
        self.knowledge.add_claim_tx(tx, subject_id=entity["id"], predicate=REPRESENTED_BY, value=src.id,
                                    status=ClaimStatus.VERIFIED, extractor=Extractor(kind="system"))
        return entity["id"]

    def _prune(self, src: Source, live_chunks: set[str], produced: set[str], actor: str) -> int:
        stale = [c for c in self.kdb["claims"].find({"evidence.source_id": src.id, "status": "proposed",
                                                     "extractor.kind": "model"})
                 if c["_id"] not in produced
                 or any(e.get("source_id") == src.id and e.get("chunk_id") not in live_chunks for e in c["evidence"])]
        if not stale:
            return 0
        removed = 0
        with self.ledger.group(actor, "extract.prune", Path(src.path).name) as tx:
            for c in stale:
                keep = [e for e in c["evidence"]
                        if e.get("source_id") != src.id or (c["_id"] in produced and e.get("chunk_id") in live_chunks)]
                if keep:
                    tx.update("claims", c["_id"], {"evidence": keep})
                else:
                    tx.delete("claims", c["_id"])
                    removed += 1
            # Auto entities left with no claims at all are noise: remove them.
            for e in tx.find("entities", {"status": "auto", "created_by": actor}):
                if not tx.find("claims", {"$or": [{"subject_id": e["id"]}, {"object_id": e["id"]}]}, limit=1):
                    tx.delete("entities", e["id"])
        return removed

    def _record_issue(self, source_id: str, chunk_id: str, reason: str, raw: str | None) -> None:
        with self.index.write() as conn:
            conn.execute(
                "INSERT INTO extraction_issues(id, source_id, chunk_id, reason, raw, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id("job"), source_id, chunk_id, reason, (raw or "")[:4000], utcnow()),
            )
