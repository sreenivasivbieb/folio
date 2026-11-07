# Extraction evaluation (golden set)

Each `golden/*.json` case is a text, optionally some already-known entities, and the claims a
correct extractor must produce. Run:

```bash
cd services/core
uv run folio-core eval ../../eval/golden --min-precision 0.8
```

The command prints precision/recall per case and exits non-zero when precision is below the gate.
CI runs it on every push (proposal: "extraction precision measured on a labeled test set before
each release; threshold set in Phase 0"). Add real, anonymised cases from your own files here —
the golden set is only as good as its coverage.
