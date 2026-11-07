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


def make_container(tmp: Path, **kw) -> Container:  # type: ignore[no-untyped-def]
    settings = Settings(data_dir=tmp / "data", watch=False, stt="none", workers=1)
    providers = Providers(llm=kw.pop("llm", FakeLLM()), embedder=HashingEmbedder(),
                          stt=kw.pop("stt", NoTranscriber("tests")))
    return build_container(settings, providers=providers, **kw)


@pytest.fixture
def container(tmp_path: Path) -> Iterator[Container]:
    c = make_container(tmp_path)
    yield c
    c.db.close()


@pytest.fixture
def files(tmp_path: Path) -> Path:
    folder = tmp_path / "files"
    folder.mkdir()
    write_samples(folder)
    return folder


def drain(c: Container) -> None:
    c.workers.run_until_idle()
