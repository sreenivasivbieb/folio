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
        self.tasks: list[str] = []

    def installed(self) -> bool:
        return True

    def transcribe(self, audio, language=None, prompt=None, on_progress=None, task="transcribe", beam_size=5):  # type: ignore[no-untyped-def]
        assert not isinstance(audio, Path) or audio.exists()
        self.prompts.append(prompt)
        self.tasks.append(task)
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
    assert stt.tasks == ["translate"]  # Hindi/Hinglish labels arrive as English
    c.labels.confirm(label.id)
    owns = repo.query_claims(c.kdb, predicate="owns")[0]
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
    src = repo.list_sources(c.kdb)[0]
    assert src.kind.value == "audio" and src.status.value == "indexed", src.error
    chunks = repo.chunks_for_source(c.index.reader(), src.id)
    assert chunks[0].locator.kind == "time" and chunks[0].locator.end == 3.0
    works = repo.query_claims(c.kdb, predicate="works_at")
    assert works and works[0].evidence[0].locator.kind == "time"


def test_misheard_transcript_can_be_corrected_in_the_preview(tmp_path):
    c = make_container(tmp_path)
    contract = c.knowledge.create_entity("Contract", "Acme contract")
    c.knowledge.create_entity("Person", "Priya")
    label = c.labels.preview("PREA owns it", "entity", [contract.id])
    assert label.parsed["questions"]  # "PREA" is unknown
    fixed = c.labels.revise(label.id, "Priya owns it")
    assert fixed.transcript == "Priya owns it" and fixed.parsed["questions"] == []
    c.labels.confirm(fixed.id)
    owns = repo.query_claims(c.kdb, predicate="owns")[0]
    assert repo.get_entity(c.kdb, owns.subject_id).name == "Priya"


def _tone_wav(path: Path, rate: int, seconds: float = 1.0) -> None:
    import numpy as np

    t = np.arange(int(rate * seconds)) / rate
    pcm = (np.sin(2 * np.pi * 440 * t) * 12000).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def test_recordings_at_any_device_rate_become_16khz(tmp_path):
    from folio_core.providers.stt.audio import SAMPLE_RATE, load_wav

    for rate in (16000, 44100, 48000):
        _tone_wav(tmp_path / f"r{rate}.wav", rate)
        audio = load_wav(tmp_path / f"r{rate}.wav")
        assert abs(audio.size - SAMPLE_RATE) <= 2 and audio.dtype.name == "float32"
        assert 0.3 < float(abs(audio).max()) < 0.4


def test_media_is_decoded_in_a_sandbox_without_system_ffmpeg(tmp_path):
    pytest.importorskip("av")
    from folio_core.providers.stt.audio import SAMPLE_RATE, decode_untrusted

    _tone_wav(tmp_path / "talk.wav", 44100, seconds=2)
    audio = decode_untrusted(tmp_path / "talk.wav", tmp_path / "out.npy", timeout_s=60, memory_mb=2048)
    assert abs(audio.size - 2 * SAMPLE_RATE) < SAMPLE_RATE // 10
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(Exception, match="cannot decode"):
        decode_untrusted(bad, tmp_path / "bad.npy", timeout_s=60, memory_mb=2048)


def test_hotkey_without_a_target_labels_the_ui_selection(tmp_path, monkeypatch):
    stt = FakeTranscriber([Segment(0.0, 1.0, "it is a Course")])
    c = make_container(tmp_path, stt=stt)
    topic = c.knowledge.create_entity("Topic", "Networks")
    monkeypatch.setattr(c.labels.recorder, "start", lambda: None)
    monkeypatch.setattr(c.labels.recorder, "stop", lambda dest: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b"x"), 2.0)[2])
    c.labels.focus = ("entity", [topic.id])  # sent by the UI via /api/voice/focus
    c.labels.start("none", [])  # e.g. `folio-core voice toggle` from a Wayland key binding
    label = c.labels.stop()
    assert label.target_kind == "entity" and label.target_ids == [topic.id]
    assert label.parsed["ops"][0]["op"] == "retype"
