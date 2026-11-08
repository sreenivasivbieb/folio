from __future__ import annotations

from fastapi import APIRouter

from ... import __version__
from ...container import Container
from ...domain.errors import InvalidInput
from ...providers.llm.openai_compat import OpenAICompatibleLLM, is_loopback
from ...providers.llm.router import PRESETS, key_name
from ...providers.privacy import cloud_enabled
from ...providers.secrets import SecretStore
from ...store import repo
from ..deps import C
from ..dto import (
    Acceptance,
    CloudBody,
    LLMSettingsBody,
    LLMSettingsView,
    LLMStatus,
    ModelsBody,
    Ok,
    PresetView,
    ProviderInfo,
    Status,
    VoiceStatus,
)

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Ok)
def health() -> Ok:
    return Ok(detail=__version__)


def llm_status(c: Container) -> LLMStatus:
    cfg = c.llm.config() if hasattr(c.llm, "config") else None
    if cfg is None:
        return LLMStatus(configured=False)
    preset = PRESETS.get(cfg.provider)
    return LLMStatus(configured=bool(cfg.model and cfg.base_url), provider=cfg.provider,
                     label=preset.label if preset else cfg.provider, base_url=cfg.base_url, model=cfg.model,
                     local=is_loopback(cfg.base_url),
                     key_hint=SecretStore.hint(c.secrets.get(key_name(cfg.provider))))


@router.get("/status", response_model=Status)
def status(c: C) -> Status:
    k, ix = c.kdb, c.index.reader()
    counts = {
        "sources": k["sources"].count_documents({"status": {"$nin": repo.HIDDEN_SOURCE_STATUSES}}),
        "entities": k["entities"].count_documents({"status": {"$nin": ["merged", "rejected"]}, "type": {"$ne": "Document"}}),
        "claims": k["claims"].count_documents({"status": {"$ne": "rejected"}, "predicate": {"$ne": "mentions"}}),
        "proposed": k["claims"].count_documents({"status": "proposed", "predicate": {"$nin": ["mentions", "represented_by"]}}),
        "chunks": ix.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
    }
    extractor = c.current_extractor()
    llm = llm_status(c)
    providers = [
        ProviderInfo(kind="extractor", model=extractor.model_id, local=not extractor.uses_llm or llm.local),
        ProviderInfo(kind="embeddings", model=c.providers.embedder.model_id, local=c.providers.embedder.is_local),
        ProviderInfo(kind="speech", model=c.providers.stt.model_id, local=c.providers.stt.is_local),
    ]
    cloud = cloud_enabled(c.kdb)
    return Status(
        version=__version__, data_dir=str(c.settings.data_dir), cloud_enabled=cloud,
        network_mode="cloud" if cloud and not all(x.local for x in providers) else "local",
        extractor=extractor.model_id, llm=llm, providers=providers, voice=VoiceStatus(**c.labels.status()),
        jobs=c.queue.counts(), counts=counts, types=c.knowledge.known_types(),
        vector_backend="sqlite-vec" if c.index.has_vec else "numpy",
        supported_extensions=c.ingestion.registry.extensions,
    )


@router.put("/settings/cloud", response_model=Ok)
def set_cloud(body: CloudBody, c: C) -> Ok:
    """Per-project cloud opt-in. Off by default; the UI shows a visible indicator when on."""
    with c.ledger.group("user", "settings.cloud", "on" if body.enabled else "off") as tx:
        tx.upsert("settings", {"id": "cloud.enabled", "value": body.enabled})
    return Ok()


# --- LLM: bring your own key --------------------------------------------------------------


@router.get("/llm", response_model=LLMSettingsView)
def get_llm(c: C) -> LLMSettingsView:
    return LLMSettingsView(status=llm_status(c), presets=[PresetView(**p.model_dump()) for p in PRESETS.values()])


@router.put("/llm", response_model=LLMSettingsView)
def put_llm(body: LLMSettingsBody, c: C) -> LLMSettingsView:
    """Choose the project's LLM. A hosted (non-loopback) endpoint is an explicit cloud opt-in."""
    if body.provider not in PRESETS:
        raise InvalidInput(f"unknown provider '{body.provider}'")
    if not body.base_url.startswith(("http://", "https://")):
        raise InvalidInput("base URL must start with http:// or https://")
    if not body.model.strip():
        raise InvalidInput("choose a model")
    if body.api_key is not None:
        c.secrets.set(key_name(body.provider), body.api_key.strip() or None)
    if PRESETS[body.provider].needs_key and not c.secrets.get(key_name(body.provider)):
        raise InvalidInput(f"{PRESETS[body.provider].label} needs an API key")
    cloud = not is_loopback(body.base_url)
    with c.ledger.group("user", "settings.llm", f"{body.provider}: {body.model}") as tx:
        tx.upsert("settings", {"id": "llm.config", "value": {
            "provider": body.provider, "base_url": body.base_url.rstrip("/"), "model": body.model.strip()}})
        if cloud:
            tx.upsert("settings", {"id": "cloud.enabled", "value": True})
    return get_llm(c)


@router.delete("/llm", response_model=LLMSettingsView)
def delete_llm(c: C) -> LLMSettingsView:
    """Back to the offline rule extractor (the stored key is kept for later)."""
    with c.ledger.group("user", "settings.llm", "none") as tx:
        tx.delete("settings", "llm.config")
        tx.upsert("settings", {"id": "cloud.enabled", "value": False})
    return get_llm(c)


@router.post("/llm/models", response_model=list[str])
def list_models(body: ModelsBody, c: C) -> list[str]:
    """The provider's live model list (so the user never has to guess model ids)."""
    key = body.api_key or c.secrets.get(key_name(body.provider))
    return OpenAICompatibleLLM(body.base_url, "probe", key).list_models()


@router.post("/llm/test", response_model=Ok)
def test_llm(c: C) -> Ok:
    """A real tiny request with the saved settings: proves key, model and JSON mode work."""
    client = c.llm.client() if hasattr(c.llm, "client") else None
    if client is None:
        raise InvalidInput("save an LLM first")
    client.ping()
    return Ok(detail=f"{client.model_id} answered")


@router.post("/extract/all", response_model=Ok)
def extract_all(c: C) -> Ok:
    """Re-run extraction on every indexed file (e.g. after choosing an LLM). Cached = free."""
    n = c.extraction.enqueue_all()
    c.workers.notify()
    return Ok(detail=f"{n} file(s) queued")


@router.post("/speech/download", response_model=Ok)
def download_speech(c: C) -> Ok:
    """Explicitly fetch the speech model (the only time Folio downloads a model)."""
    if c.providers.stt.installed():
        return Ok(detail="already installed")
    if not hasattr(c.providers.stt, "download"):
        raise InvalidInput("speech support is not installed in this build")
    c.queue.enqueue("download_speech_model", {}, dedupe_key="download_speech_model", priority=20, max_attempts=1)
    c.workers.notify()
    return Ok(detail="downloading")


@router.get("/metrics/acceptance", response_model=list[Acceptance])
def acceptance(c: C) -> list[Acceptance]:
    return [Acceptance(**r) for r in c.learning.acceptance()]
