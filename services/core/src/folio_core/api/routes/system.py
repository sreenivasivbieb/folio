from __future__ import annotations

from fastapi import APIRouter

from ... import __version__
from ...providers.privacy import cloud_enabled
from ...store.db import dumps
from ..deps import C
from ..dto import Acceptance, CloudBody, Ok, ProviderInfo, Status, VoiceStatus

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Ok)
def health() -> Ok:
    return Ok(detail=__version__)


@router.get("/status", response_model=Status)
def status(c: C) -> Status:
    p, conn = c.providers, c.db.reader()
    counts = {
        "sources": conn.execute("SELECT COUNT(*) FROM sources WHERE status != 'forgotten'").fetchone()[0],
        "entities": conn.execute("SELECT COUNT(*) FROM entities WHERE status NOT IN ('merged','rejected')").fetchone()[0],
        "claims": conn.execute("SELECT COUNT(*) FROM claims WHERE status != 'rejected'").fetchone()[0],
        "proposed": conn.execute("SELECT COUNT(*) FROM claims WHERE status = 'proposed'").fetchone()[0],
        "chunks": conn.execute("SELECT COUNT(*) FROM ix.chunks").fetchone()[0],
    }
    providers = [
        ProviderInfo(kind="extractor", model=c.extractor.model_id,
                     local=getattr(getattr(c.extractor, "llm", None), "is_local", True)),
        ProviderInfo(kind="embeddings", model=p.embedder.model_id, local=p.embedder.is_local),
        ProviderInfo(kind="speech", model=p.stt.model_id, local=p.stt.is_local),
    ]
    cloud = cloud_enabled(c.db)
    return Status(
        version=__version__, data_dir=str(c.settings.data_dir), cloud_enabled=cloud,
        network_mode="cloud" if cloud and not all(x.local for x in providers) else "local",
        providers=providers, voice=VoiceStatus(**c.labels.status()), jobs=c.queue.counts(),
        counts=counts, vector_backend="sqlite-vec" if c.db.has_vec else "numpy",
        supported_extensions=c.ingestion.registry.extensions,
    )


@router.put("/settings/cloud", response_model=Ok)
def set_cloud(body: CloudBody, c: C) -> Ok:
    """Per-project cloud opt-in. Off by default; the UI shows a visible indicator when on."""
    with c.ledger.group("user", "settings.cloud", "on" if body.enabled else "off") as tx:
        tx.upsert("settings", {"id": "cloud.enabled", "value": dumps(body.enabled)})
    return Ok()


@router.get("/metrics/acceptance", response_model=list[Acceptance])
def acceptance(c: C) -> list[Acceptance]:
    return [Acceptance(**r) for r in c.learning.acceptance()]

