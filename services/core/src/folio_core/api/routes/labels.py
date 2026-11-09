"""Voice and typed labels (FR-3): push-to-talk, preview, questions, confirm."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ...domain.errors import NotFound
from ...domain.models import Label
from ...store import repo
from ..deps import C
from ..dto import AnswerBody, Ok, Target, TranscriptBody, TypedLabel, VoiceStatus, VoiceToggle

router = APIRouter(tags=["labels"])


@router.get("/voice/status", response_model=VoiceStatus)
def voice_status(c: C) -> VoiceStatus:
    return VoiceStatus(**c.labels.status())


@router.post("/voice/start", response_model=Ok)
def voice_start(body: Target, c: C) -> Ok:
    c.labels.start(body.target_kind, body.target_ids)
    c.bus.publish({"type": "voice", "recording": True})
    return Ok()


@router.post("/voice/stop", response_model=Label)
def voice_stop(c: C) -> Label:
    c.bus.publish({"type": "voice", "recording": False})
    label = c.labels.stop()
    c.bus.publish({"type": "label", "label_id": label.id})
    return label


@router.post("/voice/cancel", response_model=Ok)
def voice_cancel(c: C) -> Ok:
    c.labels.cancel_recording()
    c.bus.publish({"type": "voice", "recording": False})
    return Ok()


@router.post("/voice/focus", response_model=Ok)
def voice_focus(body: Target, c: C) -> Ok:
    """The UI reports its selection, so a desktop hotkey (which knows nothing about the UI)
    labels the right thing."""
    c.labels.focus = (body.target_kind, body.target_ids)
    return Ok()


@router.post("/voice/toggle", response_model=VoiceToggle)
def voice_toggle(body: Target, c: C) -> VoiceToggle:
    """One endpoint for a global hotkey (e.g. a Hyprland bind calling `folio-core voice toggle`).
    The target defaults to whatever the UI has selected (sent as a 'focus' event)."""
    if c.labels.recorder.recording:
        return VoiceToggle(state="stopped", label=voice_stop(c))
    voice_start(body, c)
    return VoiceToggle(state="recording")


@router.post("/labels", response_model=Label)
def typed_label(body: TypedLabel, c: C) -> Label:
    """Keyboard path into the same pipeline as voice: transcript -> preview."""
    return c.labels.preview(body.transcript, body.target_kind, body.target_ids)


@router.get("/labels", response_model=list[Label])
def list_labels(c: C, limit: int = 50) -> list[Label]:
    return c.labels.list(limit)


@router.get("/labels/{label_id}", response_model=Label)
def get_label(label_id: str, c: C) -> Label:
    label = repo.get_label(c.kdb, label_id)
    if label is None:
        raise NotFound(f"label {label_id} not found")
    return label


@router.post("/labels/{label_id}/transcript", response_model=Label)
def revise_transcript(label_id: str, body: TranscriptBody, c: C) -> Label:
    """Correct a misheard transcript in the preview; the label is re-planned."""
    return c.labels.revise(label_id, body.transcript)


@router.post("/labels/{label_id}/answer", response_model=Label)
def answer(label_id: str, body: AnswerBody, c: C) -> Label:
    return c.labels.answer(label_id, body.question_id, body.value)


@router.post("/labels/{label_id}/confirm", response_model=Label)
def confirm(label_id: str, c: C) -> Label:
    return c.labels.confirm(label_id)


@router.post("/labels/{label_id}/cancel", response_model=Label)
def cancel(label_id: str, c: C) -> Label:
    return c.labels.cancel(label_id)


@router.get("/labels/{label_id}/audio", response_class=FileResponse)
def label_audio(label_id: str, c: C) -> FileResponse:
    return FileResponse(c.labels.audio_path(label_id), media_type="audio/wav")
