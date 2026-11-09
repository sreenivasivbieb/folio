"""Composition root: builds every service once and wires their dependencies.

Read this file to see the whole core at a glance. Nothing else constructs services; tests build
a Container with fake providers and temporary local storage.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .export import Exporter
from .extraction.llm import LLMExtractor
from .extraction.resolver import EntityResolver
from .extraction.rules import RuleBasedExtractor
from .extraction.service import ExtractionService
from .extraction.types import Extractor
from .ingestion.registry import ParserRegistry
from .ingestion.service import IngestionService
from .ingestion.vault import Vault
from .ingestion.watcher import FolderWatcher
from .jobs import Job, JobQueue, WorkerPool
from .knowledge import KnowledgeService
from .learning import CorrectionStore
from .ledger import Ledger
from .providers import Providers, build_providers
from .providers.drive import DriveService
from .providers.llm.router import ConfiguredLLM
from .providers.secrets import SecretStore
from .query.card import EntityCards
from .query.review import ReviewQueue
from .query.search import HybridSearch
from .query.views import Views
from .realtime import Bus
from .speech.labels import LabelService
from .store import IndexDB, KnowledgeDB
from .store.vectors import VectorIndex

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    kdb: KnowledgeDB
    index: IndexDB
    bus: Bus
    ledger: Ledger
    queue: JobQueue
    providers: Providers
    secrets: SecretStore
    llm: Any
    vectors: VectorIndex
    knowledge: KnowledgeService
    learning: CorrectionStore
    ingestion: IngestionService
    extraction: ExtractionService
    labels: LabelService
    search: HybridSearch
    cards: EntityCards
    views: Views
    review: ReviewQueue
    exporter: Exporter
    workers: WorkerPool
    watcher: FolderWatcher
    drive: DriveService
    vault: Vault

    def current_extractor(self) -> Extractor:
        return self.extraction.extractor()

    def start(self, background_scan: bool = True) -> None:
        for db in (self.kdb, self.index):  # before any worker writes: reclaim disk space
            db.compact()
        self.vault.root()  # Folio's own storage folder is the only place it indexes
        self.workers.start()
        if self.settings.watch:
            self.watcher.start()
        if background_scan:  # catch changes made while the app was closed
            threading.Thread(target=self.ingestion.rescan_all, name="folio-rescan", daemon=True).start()
        warm = getattr(self.providers.stt, "warm", None)
        if warm:  # load the speech model now, so the first push-to-talk is fast
            threading.Thread(target=warm, name="folio-stt-warm", daemon=True).start()

    def stop(self) -> None:
        self.watcher.stop()
        self.workers.stop()
        self.labels.cancel_recording()
        self.index.close()
        self.kdb.close()
        self.drive.close()


def build_container(settings: Settings, providers: Providers | None = None,
                    extractor: Extractor | None = None) -> Container:
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        settings.data_dir.chmod(0o700)
    kdb = KnowledgeDB(settings.data_dir / "knowledge.sqlite3")
    index = IndexDB(settings.index_db)
    bus = Bus()
    ledger = Ledger(kdb, bus)
    queue = JobQueue(index, bus)
    providers = providers or build_providers(settings)
    secrets = SecretStore(settings.secrets_file)
    llm = providers.llm if providers.llm is not None else ConfiguredLLM(kdb, secrets)

    knowledge = KnowledgeService(kdb, ledger, index)
    knowledge.ensure_schema()
    learning = CorrectionStore(kdb, providers.embedder)
    vectors = VectorIndex(index, providers.embedder.dim, providers.embedder.model_id)

    rules = RuleBasedExtractor()

    def pick_extractor() -> Extractor:
        """Fixed in tests; otherwise the project's LLM when configured, else offline rules."""
        if extractor is not None:
            return extractor
        return LLMExtractor(llm) if getattr(llm, "configured", False) else rules

    ingestion = IngestionService(
        kdb=kdb, index=index, ledger=ledger, queue=queue, bus=bus, registry=ParserRegistry(),
        embedder=providers.embedder, vectors=vectors, transcriber=providers.stt,
        settings=settings, vocabulary=learning.vocabulary_prompt,
    )
    extraction = ExtractionService(
        kdb=kdb, index=index, ledger=ledger, knowledge=knowledge, learning=learning,
        resolver=EntityResolver(knowledge, providers.embedder, index), extractor=pick_extractor, queue=queue,
    )
    labels = LabelService(kdb=kdb, index=index, ledger=ledger, knowledge=knowledge, learning=learning,
                          transcriber=providers.stt, audio_dir=settings.audio_dir, llm=llm)
    search = HybridSearch(index, kdb, providers.embedder, vectors)

    def download_speech_model(job: Job) -> str:
        stt = providers.stt
        if not hasattr(stt, "download"):
            raise RuntimeError("speech support is not installed (folio-core[speech])")
        stt.download(lambda f, m: queue.progress(job.id, f, m))
        queue.progress(job.id, 0.99, "loading the model")
        stt.warm()
        n = ingestion.requeue_media()
        bus.publish({"type": "voice"})
        return f"{stt.model_id} ready; {n} audio/video file(s) queued"

    vault = Vault(ingestion)
    workers = WorkerPool(queue, {
        "vault_import": vault.import_job,
        "scan_root": ingestion.scan_root_job,
        "index_source": ingestion.index_source,
        "extract_source": extraction.extract_source,
        "download_speech_model": download_speech_model,
    }, size=settings.workers, scan_kinds=("scan_root", "vault_import"))

    return Container(
        settings=settings, kdb=kdb, index=index, bus=bus, ledger=ledger, queue=queue,
        providers=providers, secrets=secrets, llm=llm, vectors=vectors, knowledge=knowledge,
        learning=learning, ingestion=ingestion, extraction=extraction, labels=labels, search=search,
        cards=EntityCards(kdb, search), views=Views(kdb), review=ReviewQueue(kdb, index),
        exporter=Exporter(kdb, bus), workers=workers, watcher=FolderWatcher(ingestion), drive=DriveService(secrets),
        vault=vault,
    )
