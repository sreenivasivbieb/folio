"""Time-sortable, prefixed identifiers (ULID-style), e.g. ``ent_01JC3Z...``.

The prefix makes IDs self-describing in logs, exports and the event ledger.
"""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32

PREFIXES = {
    "root": "rt",
    "source": "src",
    "chunk": "chk",
    "entity": "ent",
    "alias": "als",
    "claim": "clm",
    "evidence": "evd",
    "label": "lbl",
    "event": "evt",
    "group": "grp",
    "job": "job",
    "schema": "sch",
    "drop": "drp",
}


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def new_id(kind: str) -> str:
    """Return a new id for ``kind`` (a key of PREFIXES)."""
    prefix = PREFIXES[kind]
    ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    return f"{prefix}_{_encode(ms, 10)}{_encode(rand, 16)}"
