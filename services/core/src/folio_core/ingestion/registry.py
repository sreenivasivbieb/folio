from __future__ import annotations

import logging
from importlib.metadata import entry_points
from pathlib import Path

from ..domain.models import SourceKind
from .base import Parser
from .parsers import BUILTIN_PARSERS

log = logging.getLogger(__name__)


class ParserRegistry:
    """Maps file extensions to parsers. Plugins (entry-point group ``folio.parsers``) are loaded
    after the built-ins and may override an extension — no core code changes needed."""

    def __init__(self, parsers: list[Parser] | None = None, load_plugins: bool = True) -> None:
        self._by_name: dict[str, Parser] = {}
        self._by_ext: dict[str, Parser] = {}
        for p in parsers if parsers is not None else BUILTIN_PARSERS:
            self.register(p)
        if load_plugins:
            for ep in entry_points(group="folio.parsers"):
                try:
                    self.register(ep.load()())
                except Exception as exc:  # a broken plugin must not take the app down
                    log.warning("failed to load parser plugin %s: %s", ep.name, exc)

    def register(self, parser: Parser) -> None:
        self._by_name[parser.name] = parser
        for ext in parser.extensions:
            self._by_ext[ext.lower()] = parser

    def for_path(self, path: Path) -> tuple[Parser, SourceKind] | None:
        parser = self._by_ext.get(path.suffix.lower())
        if parser is None:
            return None
        return parser, parser.extensions[path.suffix.lower()]

    def by_name(self, name: str) -> Parser:
        return self._by_name[name]

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self._by_ext

    @property
    def extensions(self) -> list[str]:
        return sorted(self._by_ext)
