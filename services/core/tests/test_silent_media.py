"""Screen recordings often have no audio: they must still be stored, indexed, labelled and found."""

from pathlib import Path

import numpy as np
import pytest

from folio_core.store import repo

from .conftest import drain, make_container

av = pytest.importorskip("av")


def _video(path: Path, with_audio: bool = False) -> Path:
    with av.open(str(path), "w") as out:
        v = out.add_stream("mpeg4", rate=10)
        v.width, v.height, v.pix_fmt = 64, 48, "yuv420p"
        a = out.add_stream("aac", rate=16000) if with_audio else None
        for i in range(10):
            frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), i * 20, dtype=np.uint8), format="rgb24")
            for p in v.encode(frame):
                out.mux(p)
        if a is not None:
            samples = np.zeros((1, 16000), dtype=np.float32)
            af = av.AudioFrame.from_ndarray(samples, format="flt", layout="mono")
            af.sample_rate = 16000
            for p in a.encode(af):
                out.mux(p)
            for p in a.encode(None):
                out.mux(p)
        for p in v.encode(None):
            out.mux(p)
    return path


class _Speech:
    model_id, is_local = "fake-whisper", True

    def installed(self):
        return True

    def transcribe(self, *a, **k):
        return []


def test_silent_screen_recording_is_indexed_labelled_and_found(tmp_path):
    c = make_container(tmp_path / "c", stt=_Speech())
    clip = _video(tmp_path / "screenrecording-demo.mp4")
    c.vault.import_paths([str(clip)], "copy")
    drain(c)
    src = repo.list_sources(c.kdb)[0]
    assert src.status.value == "indexed" and not src.error
    assert "no audio track" in repo.chunks_for_source(c.index.reader(), src.id)[0].text
    c.labels.confirm(c.labels.preview("lexsi hackathon video demo", "source", [src.id]).id)
    assert [f["source_id"] for f in c.search.files("hackathon", [])] == [src.id]


def test_silent_video_needs_no_speech_model(tmp_path):
    from folio_core.providers.stt.unavailable import NoTranscriber

    c = make_container(tmp_path / "c", stt=NoTranscriber("not downloaded"))
    c.vault.import_paths([str(_video(tmp_path / "silent.mp4"))], "copy")
    drain(c)
    assert repo.list_sources(c.kdb)[0].status.value == "indexed"


def test_audio_without_speech_is_indexed_not_stuck(tmp_path):
    c = make_container(tmp_path / "c", stt=_Speech())
    c.vault.import_paths([str(_video(tmp_path / "quiet.mp4", with_audio=True))], "copy")
    drain(c)
    src = repo.list_sources(c.kdb)[0]
    assert src.status.value == "indexed"
    assert "no speech detected" in repo.chunks_for_source(c.index.reader(), src.id)[0].text


def test_child_errors_are_readable():
    from folio_core.providers.stt.audio import clean_child_error

    raw = (b"Traceback (most recent call last):\n  File \"x.py\", line 1\n"
           b"folio_core.domain.errors.Unavailable: clip.mp4 is damaged\n"
           b"[PYI-98920:ERROR] Failed to execute script '__main__' due to unhandled exception!\n")
    assert clean_child_error(raw) == "clip.mp4 is damaged"
