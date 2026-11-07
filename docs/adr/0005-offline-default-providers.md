# 0005 — Offline defaults: rule extractor, hashing embedder, fake LLM

**Context.** v1 must work fully offline, with zero network traffic by default, on a laptop
without a GPU. No local LLM runtime is assumed to be installed. (Decision taken with the product
owner: ship the LLM *interface* and a fake provider first.)

**Decision.**

* `providers/` defines protocols for LLM, embeddings and speech-to-text; concrete adapters are
  chosen in `providers/registry.py` from settings.
* Default extractor: `RuleBasedExtractor` — deterministic, transparent, conservative (known names,
  "Name <email>", schema relation phrases, dated sentences). Everything it produces is a
  *proposal* and goes through the same validation, resolution and review as LLM output.
* `LLMExtractor` is complete (versioned prompt, constrained JSON, quote-must-be-a-span validation,
  one retry, few-shot from corrections) and works with any OpenAI-compatible endpoint
  (Ollama/llama.cpp locally, or a cloud vendor behind the privacy opt-in). Tests drive it with
  `FakeLLM`.
* Default embedder: signed feature hashing (no download). `fastembed` (ONNX) is an extra.
* Speech: faster-whisper (`--extra speech`), multilingual `small` model by default.

**Consequences.** The whole loop runs and is testable with no model downloads. Extraction recall
with the rule extractor is limited; switching to an LLM is a configuration change.
