"""The parser plugin contract.

A parser turns one file into ``ParsedUnit``s: small pieces of text, each with a locator saying
exactly where it came from (page + region, time range, or line range). Chunking, embedding and
extraction are generic and never know which parser produced the units.

To add a file type, implement :class:`Parser` and either add it to ``parsers/__init__.py`` or
register it under the ``folio.parsers`` entry-point group from another package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..domain.models import SourceKind


@dataclass
class ParsedUnit:
    text: str
    locator: dict[str, Any]  # a Locator as a plain dict (crosses the sandbox boundary as JSON)


@dataclass
class ParseContext:
    """Capabilities a non-sandboxed parser may use (sandboxed parsers get none)."""

    transcriber: Any = None
    vocabulary_prompt: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ParseError(Exception):
    pass


class Parser(Protocol):
    name: str
    extensions: dict[str, SourceKind]  # ".pdf" -> SourceKind.PDF
    sandboxed: bool  # run in a resource-limited subprocess (untrusted bytes)

    def parse(self, path: Path, ctx: ParseContext) -> list[ParsedUnit]: ...
