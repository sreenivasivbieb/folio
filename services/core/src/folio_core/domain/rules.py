"""Rules that keep the data trustworthy (proposal, "Data model" section).

1. Every claim has at least one piece of evidence or is an explicit user assertion.
2. Re-extraction can only *propose* claims; verified or rejected claims are never silently
   changed or re-added. The **fingerprint** is how a re-extracted claim is recognised.
3. Merges rewrite no history: they are ledger events, so they can be undone and audited.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s@.\-]")


def normalize_name(name: str) -> str:
    """Case/accent/space-insensitive key used for alias lookups."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT.sub(" ", text.lower())
    text = re.sub(r"^(the|a|an)\s+", "", text.strip())
    return _WS.sub(" ", text).strip()


def normalize_value(value: Any) -> str:
    if isinstance(value, str):
        return normalize_name(value)
    return json.dumps(value, sort_keys=True, default=str)


def claim_fingerprint(
    subject_key: str, predicate: str, value: Any = None, object_key: str | None = None
) -> str:
    """Stable identity of *what* a claim says, independent of who said it or where.

    ``subject_key``/``object_key`` are entity ids. Two extractions that state the same fact about
    the same entities produce the same fingerprint, which lets re-extraction recognise facts the
    user already verified or rejected.
    """
    payload = "|".join(
        [subject_key, predicate.lower(), object_key or "", normalize_value(value) if object_key is None else ""]
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def requires_evidence(extractor_kind: str) -> bool:
    """Model claims must cite a source span; user/voice assertions are their own evidence."""
    return extractor_kind == "model"
