"""Schema and evidence checks on extractor output.

Two guarantees matter most:
1. Every type/predicate exists in the active schema.
2. Every claim's ``quote`` is literally present in the chunk text. This is the main defence against
   invented facts *and* against prompt injection: whatever text in a file says, the model can only
   produce claims that point at real spans of that file.
"""

from __future__ import annotations

import re

from ..domain.schema import MENTIONED, MENTIONS, REPRESENTED_BY, SchemaDef
from .types import CandidateClaim, ExtractionOutput

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip().lower()


def validate_output(out: ExtractionOutput, schema: SchemaDef, text: str) -> tuple[ExtractionOutput, list[str]]:
    """Return (output with only valid items, list of problems)."""
    problems: list[str] = []
    haystack = _norm(text)
    entities = []
    for e in out.entities:
        if e.type not in schema.entity_types:
            problems.append(f"entity '{e.name}': unknown type '{e.type}'")
        else:
            entities.append(e)
    claims: list[CandidateClaim] = []
    for c in out.claims:
        err = _claim_problem(c, schema, haystack)
        if err:
            problems.append(f"claim '{c.subject} {c.predicate}': {err}")
        else:
            claims.append(c)
    return ExtractionOutput(entities=entities, claims=claims), problems


def _claim_problem(c: CandidateClaim, schema: SchemaDef, haystack: str) -> str | None:
    if c.subject_type not in schema.entity_types:
        return f"unknown subject type '{c.subject_type}'"
    if not c.quote.strip() or _norm(c.quote) not in haystack:
        return "quote is not an exact span of the source text"
    if c.predicate in schema.relation_types or c.predicate == MENTIONS:
        if not c.object or not c.object_type:
            return "relation without an object"
        if c.object_type not in schema.entity_types:
            return f"unknown object type '{c.object_type}'"
        if not schema.relation_allows(c.predicate, c.subject_type, c.object_type):
            return f"'{c.predicate}' not allowed from {c.subject_type} to {c.object_type}"
        return None
    if c.predicate in (MENTIONED, REPRESENTED_BY):
        return None if c.value else "attribute without a value"
    if schema.attribute(c.subject_type, c.predicate) is None:
        return f"{c.subject_type} has no attribute '{c.predicate}'"
    if c.value is None:
        return "attribute without a value"
    return None
