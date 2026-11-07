"""Swappable model adapters. Each kind has a Protocol in ``base.py`` and several implementations;
``registry.build_providers`` picks them from Settings. Nothing else imports a concrete provider."""

from .registry import Providers, build_providers

__all__ = ["Providers", "build_providers"]
