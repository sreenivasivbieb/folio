"""``python -m folio_core`` (and the PyInstaller entry point)."""

from folio_core.main import cli

raise SystemExit(cli())
