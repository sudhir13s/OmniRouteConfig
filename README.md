# freellm

> Curated catalog of free-tier LLM + multimodal providers, with a quota-aware fallback chain so total LLM spend stays at **$0**.
>
> Vendor-neutral. Imports nothing project-specific. Drop into any Python project (FastAPI, Django, Flask, agentic pipelines, batch jobs).

[![status](https://img.shields.io/badge/status-alpha-yellow)](#status) ![python](https://img.shields.io/badge/python-3.11%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green)

---

## What it does

Given a modality (text / vision / image_gen / video_gen / embed / stt / tts) and a `task_name`, the router picks the first **free-tier** provider whose API key is present in the environment and whose daily quota isn't exhausted. On 4xx/5xx, falls through to the next provider. Returns a typed `Result` with which provider answered + cost (always `0.00`).

Catalog ships with **48 entries across 7 modalities** (Groq, Cerebras, Gemini, OpenRouter, Together, Mistral, NVIDIA NIM, SambaNova, HuggingFace, Replicate, fal.ai, Voyage, Cohere, ElevenLabs, …). All hand-curated against documented free tiers; verified monthly.

The catalog deliberately ships **multiple models per provider where rate limits are per-model** — see [Rate-limit semantics](#rate-limit-semantics) below. Each `(provider, model)` pair has its own quota counter, so rotating across models on the same provider gives effectively additive throughput.

---

## Status

`v0.2` ships:

- ✅ Catalog (48 entries across 7 modalities) — `from freellm import PROVIDERS, list_providers`
- ✅ Routing plan (`freellm.plan(modality=..., task_name=...)`) — dry-run picks the chain WITHOUT making any network call
- ✅ Persistent quota tracker (`freellm.quotas.load() / save()`) — auto-disables a provider after 3 consecutive failures
- ✅ **Config layer (NEW)** — `freellm.yaml` auto-load + `freellm.configure(...)` programmatic API. Disable providers, re-order priority, add custom providers without forking
- ✅ CLI: `python -m freellm catalog | plan | quotas | keys | version`
- ✅ Discriminated-union `FreeTier` schema (RpmRpd / TokensPerMonth / RequestsPerDay / OneTimeCredits / AlwaysFreeWithLimits)
- ✅ Pydantic v2 models, fully typed, no implicit `Any`

`v0.2` does NOT yet ship:

- ⏳ Live LiteLLM dispatch — `await call_text(...)` raises `NotImplementedError`. Fix lands in the LiteLLM-adapter PR (v0.3).

Use today for: dry-run plan inspection, catalog reads, quota state introspection, custom config layering, CLI tooling. Library shape is locked — v0.3 adds runtime without breaking the contract.

---

## Install

```bash
# v0.1 (no PyPI yet — install from git)
pip install "freellm @ git+https://github.com/sudhir13s/freellm.git@main"

# editable / local
pip install -e .
```

For the runtime extras (LiteLLM, httpx) once `v0.2` ships:

```bash
pip install "freellm[runtime] @ git+https://github.com/sudhir13s/freellm.git@main"
```

For YAML config support (`v0.2`):

```bash
pip install "freellm[yaml] @ git+https://github.com/sudhir13s/freellm.git@main"
```

---

## Quickstart

```python
from freellm import plan, list_providers

# Show every text provider in the catalog (10 entries)
for entry in list_providers("text"):
    print(entry.provider, entry.model, entry.env_var)

# Dry-run the routing plan for a text call given current env vars.
# Returns Plan(options=[...], chosen=PlanOption | None).
p = plan(modality="text", task_name="extract-record")
if p.chosen:
    print(f"Will route to {p.chosen.provider}/{p.chosen.model}")
else:
    print("No provider available — set at least one env var (e.g. GROQ_API_KEY)")
```

```python
# v0.2 — actual call (currently raises NotImplementedError):
import asyncio
from freellm import call_text

async def main():
    result = await call_text(
        messages=[{"role": "user", "content": "Summarize: ..."}],
        task_name="summarize",
    )
    print(f"answered by {result.provider_used}/{result.model_used} in {result.latency_ms}ms")
    print(result.content)

asyncio.run(main())
```

---

## Environment variables

Set ONE OR MORE of the following. Each missing key is silently dropped from the chain at startup; the catalog still loads.

| Modality | Provider | Env var |
|---|---|---|
| text / vision / stt | Groq | `GROQ_API_KEY` |
| text | Cerebras | `CEREBRAS_API_KEY` |
| text / vision / embed | Google AI Studio (Gemini) | `GEMINI_API_KEY` |
| text / vision / image_gen | OpenRouter | `OPENROUTER_API_KEY` |
| text / image_gen | Together AI | `TOGETHER_API_KEY` |
| text / embed | Mistral | `MISTRAL_API_KEY` |
| text / image_gen / embed / stt / tts | HuggingFace Inference | `HF_TOKEN` |
| image_gen / video_gen | Replicate | `REPLICATE_API_TOKEN` |
| image_gen / video_gen | fal.ai | `FAL_API_KEY` |
| embed | Voyage | `VOYAGE_API_KEY` |
| embed / rerank | Cohere | `COHERE_API_KEY` |
| tts | ElevenLabs | `ELEVENLABS_API_KEY` |

A paid key (e.g. `OPENAI_API_KEY`) is allowed but **never** auto-inserted into a chain. Opt in via `LLM_ALLOW_PAID=1`.

Run `python -m freellm keys` to see which keys are detected without exposing values.

---

## CLI

```bash
python -m freellm version              # 0.1.0
python -m freellm catalog              # all 28 entries
python -m freellm catalog --modality text
python -m freellm plan --modality image_gen --task-name "demo"
python -m freellm keys                 # which env vars are set (no values)
python -m freellm quotas               # persisted per-provider counters
```

---

## Quota persistence

Per-provider per-day counters live at `${FREELLM_QUOTA_DIR:-data/freellm}/quotas.json`. Use `freellm.quotas.{load, save, record_success, record_failure}` to interact programmatically. Auto-disable kicks in after 3 consecutive failures (configurable).

Concurrent writes from multiple processes are NOT safe today — quota state is a single JSON file. If you need multi-process safety, either:
- Run a single dispatcher process (recommended; agentic pipelines naturally do this)
- Override `FREELLM_QUOTA_DIR` per-worker

---

## Architecture

```
freellm/
├─ schemas.py     # Pydantic v2 — ProviderEntry, FreeTier (discriminated union),
│                 #   Modality, Plan, PlanOption, Result
├─ providers.py   # Curated catalog: PROVIDERS dict[Modality, list[ProviderEntry]]
├─ quotas.py      # Persistent per-provider per-day counter
├─ router.py      # Filtering + dry-run plan() + (v0.2) live call_*
├─ cli.py         # `python -m freellm`
├─ __main__.py
├─ __init__.py    # Public re-exports
└─ tests/
```

Design rules:
- LiteLLM is the only provider SDK we depend on (v0.2). Everything else is pure Python.
- The catalog is the source of truth; agents/dashboards SHOULD NOT redefine provider lists.
- Adding a provider = appending one `ProviderEntry` row + a unit test. No other code touches.

---

## Modalities covered

| Modality | What | Entries in catalog |
|---|---|---|
| `text` | Chat / completion | **26** (Groq×5, Gemini×4, OpenRouter×4, Cerebras×3, NVIDIA NIM×3, Mistral×3, Together×2, SambaNova×1, HF×1) |
| `vision` | Text + image input → text output | **5** (Groq×2, OpenRouter×2, Gemini×1) |
| `image_gen` | Text → image | 4 |
| `video_gen` | Text → short video | 2 |
| `embed` | Text → embedding vector | 5 |
| `stt` | Speech → text | **4** (Groq×3, HF×1) |
| `tts` | Text → speech | 2 |

## Rate-limit semantics

Free-tier providers fall into two camps:

- **Per-model rate limits** (Groq, Cerebras, Gemini, OpenRouter `:free`, NVIDIA NIM, Mistral, partly Together) — every `(provider, model)` pair has its own RPM/RPD/token pool. Rotating across models on the same provider gives **effectively additive throughput** without spending a cent more. The catalog deliberately ships multiple models per provider here. `quotas.py` keys on `provider:model` (not `provider`) so the auto-disable + counter logic respects this.

  Concrete example: Groq's free tier gives `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `llama-3.2-3b-preview`, `mixtral-8x7b-32768`, and `gemma2-9b-it` each their own 14,400 RPD pool. With one Groq API key you get **5 × 14,400 = 72,000 free text req/day** before the chain rotates to Cerebras, Gemini, etc.

- **Per-account rate limits** (HuggingFace Inference, Cohere, Voyage, Replicate, fal.ai, ElevenLabs, SambaNova) — single shared pool or credit balance for the whole account. Multi-model rotation does NOT help. Catalog ships one canonical entry per such provider per modality.

The fallback chain order built into the catalog is:

1. **Same provider, sibling model** (additive throughput where supported).
2. **Next provider with sibling models** (per-model pools).
3. **Per-account-pool providers** (HF / Cohere / Voyage / etc.) at the tail.

Override the order per modality via `freellm.configure(order={"text": ["cerebras", "groq", ...]})`.

Out of scope: GPU compute (Colab / Kaggle / RunPod) — those are notebook UIs, not API-callable. Track them in your application layer.

---

## License

MIT. Catalog data ships under CC-BY-4.0 (give credit if you republish the curated list).

---

## Configuration

Three layers, in precedence order (last wins):

### 1. Built-in catalog
Ships in `freellm/providers.py`. Always loaded.

### 2. YAML config file (auto-loaded)
Drop a `freellm.yaml` in your CWD or set `FREELLM_CONFIG_PATH`:

```yaml
disable:
  - replicate              # we hit Replicate's quota; skip entirely

order:
  text:
    - cerebras             # try Cerebras first; faster than Groq for our prompts
    - groq
    - gemini

extra_providers:
  text:
    - provider: my_proxy
      model: my-llama-70b
      env_var: MY_PROXY_KEY
      speed_tier: fast
      last_verified: "2026-04-26"
      free_tier:
        kind: rpm_rpd
        rpm: 60
        rpd: 100000
```

Auto-load happens at import time. Opt out with `FREELLM_NO_AUTO_LOAD=1`.

### 3. Programmatic API
```python
import freellm

freellm.configure(
    disable=["replicate"],
    order={"text": ["cerebras", "groq", "gemini"]},
    extra_providers={"text": [{...}]},
)

# Inspect
cfg = freellm.get_config()
print(cfg.total_entries, cfg.disabled, cfg.order)

# Restore built-in defaults (useful in tests)
freellm.reset()
```

Three layers compose cleanly: built-in catalog → YAML overrides → programmatic overrides. Calling `configure()` twice is additive, not replacing — pass `reset_first=True` to start fresh.

---

## Roadmap

- `v0.2` ✅ Config layer + per-model catalog expansion (this release)
- `v0.3` — LiteLLM adapter + live `call_*` runtime
- `v0.4` — `estimate_cost_and_eta()` for media-benchmark use case + calibration agent
- `v1.0` — PyPI publish + stable API guarantee
