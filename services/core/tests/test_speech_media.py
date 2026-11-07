"""Voice capture -> transcript -> preview, and audio/video transcription with time locators.
The microphone and Whisper are replaced by fakes; ffmpeg and everything else is real."""

import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from folio_core.providers.stt.base import Segment
from folio_core.store import repo

from .conftest import drain, make_container


class FakeTranscriber:
    model_id = "fake-whisper"
    is_local = True

    def __init__(self, segments: list[Segment]) -> None:
        self.segments = segments
        self.prompts: list[str | None] = []

    def transcribe(self, audio_path: Path, language=None, prompt=None):  # type: ignore[no-untyped-def]
        assert audio_path.exists()
        self.prompts.append(prompt)
        return self.segments


def test_push_to_talk_produces_a_preview_with_audio_evidence(tmp_path, monkeypatch):
    stt = FakeTranscriber([Segment(0.0, 2.5, "Priya owns it")])
    c = make_container(tmp_path, stt=stt)
    priya = c.knowledge.create_entity("Person", "Priya")
    contract = c.knowledge.create_entity("Contract", "Acme contract")

    def fake_stop(dest: Path) -> float:  # what MicRecorder writes: 16 kHz mono WAV
        dest.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dest), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000 * 2)
        return 2.0

    monkeypatch.setattr(c.labels.recorder, "start", lambda: None)
    monkeypatch.setattr(c.labels.recorder, "stop", fake_stop)
    c.labels.start("entity", [contract.id])
    label = c.labels.stop()

    assert label.transcript == "Priya owns it"
    assert label.audio_path and Path(label.audio_path).exists()
    assert stt.prompts[0] and "Priya" in stt.prompts[0]  # personal vocabulary biases recognition
    c.labels.confirm(label.id)
    owns = repo.query_claims(c.db.reader(), predicate="owns")[0]
    assert owns.subject_id == priya.id and owns.extractor.kind == "voice"
    assert c.labels.audio_path(label.id).exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_audio_file_is_transcribed_with_timestamps(tmp_path, files):
    audio = tmp_path / "standup.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    str(audio)], check=True)
    stt = FakeTranscriber([Segment(0.0, 1.5, "Rahul Verma works at Acme Corp."),
                           Segment(1.5, 3.0, "The Atlas Project kicked off on May 4, 2026.")])
    c = make_container(tmp_path / "c", stt=stt)
    c.ingestion.add_root(str(audio))
    drain(c)
    src = repo.list_sources(c.db.reader())[0]
    assert src.kind.value == "audio" and src.status.value == "indexed", src.error
    chunks = repo.chunks_for_source(c.db.reader(), src.id)
    assert chunks[0].locator.kind == "time" and chunks[0].locator.end == 3.0
    works = repo.query_claims(c.db.reader(), predicate="works_at")
    assert works and works[0].evidence[0].locator.kind == "time"
