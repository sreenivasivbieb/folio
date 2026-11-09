"""Test fixtures use private temporary local files; no server or cloud account is required."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from folio_core.config import Settings
from folio_core.container import Container, build_container
from folio_core.providers import Providers
from folio_core.providers.embeddings.hashing import HashingEmbedder
from folio_core.providers.llm.fake import FakeLLM
from folio_core.providers.stt.unavailable import NoTranscriber

from .samples import write_samples

_created: list[Container] = []


def make_container(tmp: Path, db_name: str | None = None, **kw) -> Container:  # type: ignore[no-untyped-def]
    settings = Settings(data_dir=tmp / "data", watch=False, stt="none", workers=1)
    providers = Providers(embedder=HashingEmbedder(), stt=kw.pop("stt", NoTranscriber("tests")),
                          llm=kw.pop("llm", FakeLLM()))
    c = build_container(settings, providers=providers, **kw)
    _created.append(c)
    return c


@pytest.fixture(autouse=True)
def _drop_test_databases() -> Iterator[None]:
    yield
    while _created:
        c = _created.pop()
        c.kdb.drop()
        c.kdb.close()
        c.index.close()


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return make_container(tmp_path)


@pytest.fixture
def files(tmp_path: Path) -> Path:
    folder = tmp_path / "files"
    folder.mkdir()
    write_samples(folder)
    return folder


def drain(c: Container) -> None:
    c.workers.run_until_idle()


def entity_name(c: Container, entity_id: str) -> str:
    return c.kdb["entities"].find_one({"_id": entity_id})["name"]
