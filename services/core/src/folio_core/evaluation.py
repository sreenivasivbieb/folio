"""Extraction quality on a labeled golden set (proposal: "Trust" NFR and the Phase 0 gate).

Each case in ``eval/golden/*.json`` is::

    {"text": "...", "known": [{"name": "Acme Corp", "type": "Organization"}],
     "expected": [{"subject": "Priya", "predicate": "owns", "object": "Acme Contract"},
                  {"subject": "Acme Contract", "predicate": "signed_on", "value": "2026-03-03"}]}

Precision = correct proposed claims / all proposed claims; recall = found / expected.
Document mentions are excluded (they are trivially correct string matches).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain.rules import normalize_name
from .domain.schema import MENTIONED, MENTIONS, load_pack
from .extraction.rules import RuleBasedExtractor
from .extraction.types import ExtractionContext
from .extraction.types import Extractor as ExtractorProto
from .extraction.validate import validate_output
from .learning import GazetteerEntry


def _key(subject: str, predicate: str, obj: str | None, value: Any) -> tuple[str, str, str]:
    target = normalize_name(obj) if obj else normalize_name(str(value))
    return normalize_name(subject), predicate, target


def run_eval(golden_dir: Path, extractor: ExtractorProto | None = None) -> dict[str, Any]:
    extractor = extractor or RuleBasedExtractor()
    schema = load_pack()
    tp = fp = fn = 0
    cases = []
    for path in sorted(golden_dir.glob("*.json")):
        case = json.loads(path.read_text())
        gaz = [GazetteerEntry(k["name"], normalize_name(k["name"]), f"k{i}", k["type"], k["name"], "verified")
               for i, k in enumerate(case.get("known", []))]
        ctx = ExtractionContext(schema=schema, gazetteer=sorted(gaz, key=lambda g: -len(g.normalized)),
                                document_name=path.stem)
        out, _ = validate_output(extractor.extract(case["text"], ctx), schema, case["text"])
        got = {_key(c.subject, c.predicate, c.object, c.value) for c in out.claims
               if c.predicate not in (MENTIONS, MENTIONED)}
        want = {_key(e["subject"], e["predicate"], e.get("object"), e.get("value")) for e in case["expected"]}
        c_tp, c_fp, c_fn = len(got & want), len(got - want), len(want - got)
        tp, fp, fn = tp + c_tp, fp + c_fp, fn + c_fn
        cases.append({"case": path.stem, "tp": c_tp, "fp": c_fp, "fn": c_fn,
                      "missed": sorted(map(list, want - got)), "extra": sorted(map(list, got - want))})
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"extractor": extractor.model_id, "precision": round(precision, 3),
            "recall": round(recall, 3), "cases": cases}
