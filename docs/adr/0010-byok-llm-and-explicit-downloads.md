# 0010 — Bring-your-own-key LLM routing; models download only on request

**Status.** Accepted (2026-11-08). Refines [0005](0005-offline-default-providers.md).

**Context.** On real documents the offline rule extractor found nothing (5 files, 122 passages,
0 facts), so the graph stayed empty. The product owner wants a router-based LLM where anyone
brings their own API key — OpenAI, OpenRouter, Qwen and others. Separately, the speech model was
being downloaded silently inside an indexing job (a 20-minute video sat "running" with no
progress while ~460 MB downloaded), contradicting "zero network traffic by default".

**Decision.**

* `providers/llm/router.py`: presets for OpenRouter, OpenAI, Qwen (Alibaba Cloud), Groq, Ollama
  and any custom OpenAI-compatible URL (e.g. a hackathon router). The project stores provider,
  base URL and model in `settings`; the **API key** goes to `<data_dir>/secrets.json` (0600) and
  never into MongoDB, the ledger, exports or API responses (only a `…abcd` hint).
* The extractor is chosen per job: LLM when configured, rules otherwise. Choosing a hosted
  provider is an explicit cloud opt-in, shown permanently in the top bar.
* `OpenAICompatibleLLM` handles provider differences: `json_schema` → `json_object` fallback
  (remembered per provider), code-fence stripping, retries with backoff on 429/5xx, clear errors
  for bad keys/models; `GET /models` powers the model picker; "Test" makes one real request.
* Speech models are fetched only by the user's explicit "Download speech model" action (a job
  with byte-level progress). Without the model, audio/video wait with a clear status and are
  re-queued automatically once it is installed. Long transcriptions report progress.

**Consequences.** Real extraction quality depends on the chosen model; costs are bounded by the
per-chunk cache (re-runs on unchanged files are free). Default mode still sends nothing anywhere.
