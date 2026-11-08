"""Trust checks on extractor output (open schema: types and predicates are free-form).

The guarantee that matters most: every claim's ``quote`` is literally present in the chunk text.
That is the main defence against invented facts *and* against prompt injection — whatever text in
a file says, the model can only produce claims that point at real spans of that file.
"""

from __future__ import annotations

import re

from ..domain.schema import MENTIONED, MENTIONS, REPRESENTED_BY, SchemaDef
from .types import CandidateClaim, ExtractionOutput

_WS = re.compile(r"\s+")
MAX_NAME = 120


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip().lower()


def validate_output(out: ExtractionOutput, schema: SchemaDef | None, text: str) -> tuple[ExtractionOutput, list[str]]:
    """Return (output with only valid items, list of problems). ``schema`` is only a hint."""
    del schema  # open schema: hints never reject anything
    problems: list[str] = []
    haystack = _norm(text)
    entities = [e for e in out.entities if e.name.strip() and e.type.strip() and len(e.name) <= MAX_NAME]
    claims: list[CandidateClaim] = []
    for c in out.claims:
        err = _claim_problem(c, haystack)
        if err:
            problems.append(f"claim '{c.subject} {c.predicate}': {err}")
        else:
            claims.append(c)
    return ExtractionOutput(entities=entities, claims=claims), problems


def _claim_problem(c: CandidateClaim, haystack: str) -> str | None:
    if not c.subject.strip() or len(c.subject) > MAX_NAME:
        return "missing or overlong subject"
    if not c.subject_type.strip() or not c.predicate.strip():
        return "missing subject type or predicate"
    if not c.quote.strip() or _norm(c.quote) not in haystack:
        return "quote is not an exact span of the source text"
    if c.object is not None or c.object_type is not None or c.predicate == MENTIONS:
        if not (c.object or "").strip() or not (c.object_type or "").strip():
            return "relation without an object name and type"
        if len(c.object or "") > MAX_NAME:
            return "overlong object name"
        return None
    if c.predicate in (MENTIONED, REPRESENTED_BY):
        return None if c.value else "attribute without a value"
    if c.value is None or not str(c.value).strip():
        return "attribute without a value"
    return None
