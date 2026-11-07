"""Composition root: builds every service once and wires their dependencies.

Read this file to see the whole core at a glance. Nothing else constructs services; tests build
a Container with fake providers.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from .config import Settings
from .export import Exporter
from .extraction.llm import LLMExtractor
from .extraction.resolver import EntityResolver
from .extraction.rules import RuleBasedExtractor
from .extraction.service import ExtractionService
from .extraction.types import Extractor
from .ingestion.registry import ParserRegistry
from .ingestion.service import IngestionService
from .ingestion.watcher import FolderWatcher
from .jobs import JobQueue, WorkerPool
from .knowledge import KnowledgeService
from .learning import CorrectionStore
from .ledger import Ledger
from .providers import Providers, build_providers
from .query.card import EntityCards
from .query.review import ReviewQueue
from .query.search import HybridSearch
from .query.views import Views
from .realtime import Bus
from .speech.labels import LabelService
from .store import Database
from .store.vectors import VectorIndex

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    db: Database
    bus: Bus
    ledger: Ledger
    queue: JobQueue
    providers: Providers
    extractor: Extractor
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

    def start(self, background_scan: bool = True) -> None:
        self.workers.start()
        if self.settings.watch:
            self.watcher.start()
        if background_scan:  # catch changes made while the app was closed
            threading.Thread(target=self.ingestion.rescan_all, name="folio-rescan", daemon=True).start()

    def stop(self) -> None:
        self.watcher.stop()
        self.workers.stop()
        self.labels.cancel_recording()
        self.db.close()


def build_container(settings: Settings, providers: Providers | None = None,
                    extractor: Extractor | None = None) -> Container:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.knowledge_db, settings.index_db)
    bus = Bus()
    ledger = Ledger(db, bus)
    queue = JobQueue(db, bus)
    providers = providers or build_providers(settings)

    knowledge = KnowledgeService(db, ledger)
    knowledge.ensure_schema()
    learning = CorrectionStore(db, providers.embedder)
    vectors = VectorIndex(db, providers.embedder.dim, providers.embedder.model_id)

    if extractor is None:
        extractor = LLMExtractor(providers.llm) if settings.extractor == "llm" else RuleBasedExtractor()

    ingestion = IngestionService(
        db=db, ledger=ledger, queue=queue, bus=bus, registry=ParserRegistry(),
        embedder=providers.embedder, vectors=vectors, transcriber=providers.stt,
        settings=settings, vocabulary=learning.vocabulary_prompt,
    )
    extraction = ExtractionService(
        db=db, ledger=ledger, knowledge=knowledge, learning=learning,
        resolver=EntityResolver(knowledge, providers.embedder), extractor=extractor, queue=queue,
    )
    labels = LabelService(db=db, ledger=ledger, knowledge=knowledge, learning=learning,
                          transcriber=providers.stt, audio_dir=settings.audio_dir)
    search = HybridSearch(db, providers.embedder, vectors)
    workers = WorkerPool(queue, {
        "index_source": ingestion.index_source,
        "extract_source": extraction.extract_source,
    }, size=settings.workers)

    return Container(
        settings=settings, db=db, bus=bus, ledger=ledger, queue=queue, providers=providers,
        extractor=extractor, knowledge=knowledge, learning=learning, ingestion=ingestion,
        extraction=extraction, labels=labels, search=search, cards=EntityCards(db, search),
        views=Views(db), review=ReviewQueue(db), exporter=Exporter(db, bus), workers=workers,
        watcher=FolderWatcher(ingestion),
    )
