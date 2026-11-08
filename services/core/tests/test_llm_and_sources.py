"""Bring-your-own-key LLM routing, provider fallbacks, and source lifecycle fixes."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from folio_core.api.app import create_app
from folio_core.domain.errors import InvalidInput
from folio_core.ingestion.chunker import clean_text
from folio_core.providers.llm.openai_compat import OpenAICompatibleLLM
from folio_core.providers.llm.router import ConfiguredLLM
from folio_core.store import repo

from .conftest import drain, make_container

TOKEN = "t"


def test_provider_falls_back_from_json_schema_and_strips_fences():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body.get("response_format", {}).get("type"))
        assert request.headers["authorization"] == "Bearer sk-test"
        if body.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": {"message": "json_schema is not supported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}]})

    llm = OpenAICompatibleLLM("https://router.example/v1", "m", "sk-test", transport=httpx.MockTransport(handler))
    assert not llm.is_local
    assert json.loads(llm.complete_json("s", "u", {"type": "object"})) == {"ok": True}
    assert seen == ["json_schema", "json_object"]
    llm.complete_json("s", "u", {"type": "object"})
    assert seen[-1] == "json_object"  # remembered: no wasted json_schema attempt


def test_provider_reports_a_bad_key_clearly():
    llm = OpenAICompatibleLLM("https://router.example/v1", "m", "bad",
                              transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"message": "invalid key"}})))
    with pytest.raises(InvalidInput, match="rejected the API key"):
        llm.complete_json("s", "u", {})


def test_llm_settings_api_keeps_the_key_secret_and_opts_into_cloud(tmp_path):
    c = make_container(tmp_path, llm=None)  # production wiring: ConfiguredLLM
    assert isinstance(c.llm, ConfiguredLLM) and not c.llm.configured
    assert c.current_extractor().model_id == "rules-v1"
    with TestClient(create_app(c, TOKEN, start_background=False)) as tc:
        tc.headers["Authorization"] = f"Bearer {TOKEN}"
        presets = {p["id"] for p in tc.get("/api/llm").json()["presets"]}
        assert {"openai", "openrouter", "qwen", "groq", "ollama", "custom"} <= presets

        r = tc.put("/api/llm", json={"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "qwen/qwen-2.5-72b-instruct"})
        assert r.status_code == 422 and "API key" in r.json()["detail"]

        r = tc.put("/api/llm", json={"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1",
                                     "model": "qwen/qwen-2.5-72b-instruct", "api_key": "sk-or-1234567890abcd"})
        assert r.status_code == 200
        status = r.json()["status"]
        assert status["configured"] and not status["local"] and status["key_hint"] == "…abcd"
        assert "sk-or" not in r.text  # the key never comes back
        assert tc.get("/api/status").json()["cloud_enabled"] is True  # choosing a hosted LLM = opt-in
        assert c.current_extractor().model_id == "openrouter:qwen/qwen-2.5-72b-instruct"

    exported = json.dumps(c.exporter.to_json())
    assert "sk-or" not in exported  # keys never reach the database or exports
    assert (c.settings.secrets_file.stat().st_mode & 0o777) == 0o600

    with TestClient(create_app(c, TOKEN, start_background=False)) as tc:
        tc.headers["Authorization"] = f"Bearer {TOKEN}"
        tc.delete("/api/llm")
        assert c.current_extractor().model_id == "rules-v1"
        assert tc.get("/api/status").json()["cloud_enabled"] is False


def test_removing_a_folder_hides_its_files_but_keeps_knowledge(container, files):
    root = container.ingestion.add_root(str(files))
    drain(container)
    claims_before = container.kdb["claims"].count_documents({})
    assert repo.list_sources(container.kdb)
    container.ingestion.remove_root(root.id)
    assert repo.list_sources(container.kdb) == []
    assert container.index.reader().execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    assert container.kdb["claims"].count_documents({}) == claims_before
    container.ingestion.add_root(str(files))  # adding it back brings the files back
    drain(container)
    assert len(repo.list_sources(container.kdb)) == 5


def test_pdf_symbol_glyphs_are_cleaned():
    assert clean_text(" Understand the OSI model\n  Illustrate  layers�") == \
        "Understand the OSI model\nIllustrate layers"


def test_media_waits_for_the_speech_model_instead_of_downloading(tmp_path):
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")

    class NotDownloaded:
        model_id, is_local = "fake-whisper", True

        def installed(self):
            return False

        def transcribe(self, *a, **k):
            raise AssertionError("must not transcribe (or download) without the model")

    audio = tmp_path / "talk.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", str(audio)], check=True)
    c = make_container(tmp_path / "c", stt=NotDownloaded())
    c.ingestion.add_root(str(audio))
    drain(c)
    src = repo.list_sources(c.kdb)[0]
    assert src.status.value == "failed" and "speech model not downloaded" in src.error
    assert c.labels.status()["speech_available"] is False
