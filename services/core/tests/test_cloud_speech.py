"""Voice and audio/video through the connected provider's Whisper API (Groq/OpenAI)."""

import json

import httpx
import numpy as np

from folio_core.providers.llm.openai_compat import OpenAICompatibleLLM
from folio_core.providers.stt.audio import SAMPLE_RATE
from folio_core.providers.stt.cloud_stt import CHUNK_S, CloudWhisper, HybridTranscriber
from folio_core.providers.stt.unavailable import NoTranscriber


class _Router:
    def __init__(self, client):
        self._c = client

    def client(self):
        return self._c


def _groq(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("latin-1")
        model = "whisper-large-v3" if 'name="model"\r\n\r\nwhisper-large-v3\r\n' in body else "turbo"
        seen.append((request.url.path, model))
        return httpx.Response(200, json={"segments": [{"start": 1.0, "end": 2.0, "text": " hello kites "}]})
    return OpenAICompatibleLLM("https://api.groq.com/openai/v1", "llama", "k", transport=httpx.MockTransport(handler))


def test_long_audio_is_chunked_with_correct_timestamps():
    seen = []
    cloud = CloudWhisper(_Router(_groq(seen)))
    audio = np.zeros(int((CHUNK_S + 30) * SAMPLE_RATE), dtype=np.float32)  # just over one chunk
    segs = cloud.transcribe(audio)
    assert [s.start for s in segs] == [1.0, CHUNK_S + 1.0]
    assert segs[0].text == "hello kites"
    assert {p for p, _ in seen} == {"/openai/v1/audio/transcriptions"}


def test_voice_labels_translate_to_english(tmp_path):
    seen = []
    wav = tmp_path / "label.wav"
    wav.write_bytes(b"RIFF....WAVE")
    CloudWhisper(_Router(_groq(seen))).transcribe(wav, task="translate")
    assert seen == [("/openai/v1/audio/translations", "whisper-large-v3")]


def test_hybrid_prefers_local_and_falls_back_to_cloud():
    cloud = CloudWhisper(_Router(_groq([])))
    hybrid = HybridTranscriber(NoTranscriber("not downloaded"), cloud)
    assert hybrid.installed() and not hybrid.is_local and "whisper" in hybrid.model_id
    no_cloud = HybridTranscriber(NoTranscriber("not downloaded"), CloudWhisper(_Router(None)))
    assert not no_cloud.installed()


def test_providers_without_a_speech_api_are_not_used():
    openrouter = OpenAICompatibleLLM("https://openrouter.ai/api/v1", "m", "k")
    assert not CloudWhisper(_Router(openrouter)).available()
    assert json.dumps({"ok": True})


def test_silence_and_noise_do_not_become_labels():
    from folio_core.providers.stt.cloud_stt import _is_speech

    assert not _is_speech({"text": "."}) and not _is_speech({"text": " "})
    assert not _is_speech({"text": "Thank you.", "no_speech_prob": 0.9})
    assert _is_speech({"text": "lexsi demo", "no_speech_prob": 0.1})
