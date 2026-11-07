"""Schema-guided extraction of entities and claims (FR-4).

    types.py      candidate models (also the JSON schema given to an LLM) + Extractor protocol
    rules.py      offline deterministic extractor (default)
    llm.py        LLM extractor: versioned prompt, constrained JSON, one retry
    validate.py   schema + "quote must be a real span" checks
    resolver.py   candidate name -> entity id; merge suggestions
    service.py    the extract_source job: caching, writing proposals, pruning stale ones
"""
