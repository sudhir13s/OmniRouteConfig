# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`OmniRouteConfig` (Python import: `omni_route_config`) is a Python **configuration + lifecycle helper** for [OmniRoute](https://github.com/sudhir13s/OmniRoute), a separate Node.js LLM-router service. This package does **no inference and owns no routing logic** — it reads a curated YAML catalog of free-tier providers, matches each entry against env vars holding API keys, and POSTs the runnable subset to a running OmniRoute instance via `/api/providers`. It also ships a thin OpenAI-SDK adapter pre-pointed at OmniRoute's `/api/v1` proxy.

When editing here, the mental model is: *we write config TO OmniRoute, we do not replace it.*

## Common commands

```bash
# Editable install with dev + optional OpenAI client
pip install -e ".[dev,client]"

# Lint (ruff is the single tool — replaces black/isort/flake8)
ruff check omni_route_config/
ruff format omni_route_config/

# Type check (strict mode is the floor — see pyproject for rules)
mypy omni_route_config/

# Tests (pytest-asyncio in `auto` mode — async tests don't need a marker)
pytest -v
pytest omni_route_config/tests/test_bootstrap.py -v
pytest -k "test_apply_config_handles_already_present"    # single test by name

# CLI smoke (also what CI runs)
python -m omni_route_config version
python -m omni_route_config catalog
omniroutectl status                 # primary CLI binary
```

CI mirrors this exactly across Python 3.11, 3.12, 3.13 (see `.github/workflows/ci.yml`). If `ruff check` fails locally, CI will fail.

## Architecture (the parts that span files)

Six modules in `omni_route_config/`. Each owns one concern; combined they implement the bootstrap → configure → use loop plus live discovery.

```
catalog.py    YAML  ──▶  Pydantic ProviderCatalog       (pure parsing, no I/O beyond fs read)
                          │
                          ▼
bootstrap.py  ─── ensure_running()  ──▶  detect/spawn OmniRoute (existing → npx → docker)
              ─── apply_config()    ──▶  POST runnable entries to /api/providers
              ─── status() / tear_down() / destroy_volume()
                          │
                          ▼
registry.py   ─── fetch_registry() ──▶  GET /api/v1/models + /api/providers, join, classify
              ─── get_registry()   ──▶  cache-first (24h TTL at .omniroute/registry.json)
client.py     openai_for_omniroute() ──▶  openai.OpenAI(base_url=<omni>/api/v1, ...)
types.py      Public Pydantic models: OmniRouteStatus, ProviderApply, ApplyResult,
              ModelEntry, ProviderRegistry, ModelType, SyncDiff
cli.py        argparse façade over the above; sync subcommands + async-via-asyncio.run
```

### Catalog precedence (read by `load_catalog`)
1. Explicit `path` argument
2. `OMNI_ROUTE_CONFIG_PATH` env var
3. Bundled default at `omni_route_config/free-providers.yaml` (resolved via `Path(__file__).parent` so it works in dev AND in pip-installed wheels)

`provider` field in YAML **must** match an OmniRoute provider id (see `OmniRoute/src/shared/constants/providers.ts` upstream — that's the authoritative list). Adding a row here without the upstream id = silent 4xx at apply time.

### Three launch strategies in `ensure_running`
Tried in order from `prefer` tuple, default `("existing", "npx", "docker")`:
- `existing` — health-probe `OMNIROUTE_URL`. If reachable, no spawn.
- `npx` — `npx -y omniroute@latest --no-open --port <p>`; PID stashed in `.omniroute/pid`.
- `docker` — `docker run -d --name omniroute --restart unless-stopped -v omniroute-data:/app/data --env-file .env diegosouzapw/omniroute:latest`.

Health probes hit `/api/init` and `/` in that order — verified against OmniRoute v3.7.x. `/api/health` and `/api/version` do NOT exist upstream. `tear_down()` only kills processes spawned by THIS package (PID file gated) — externally-started instances are never touched.

### Idempotency contract (must preserve when editing `bootstrap.apply_config`)
- Missing env var → `skipped_missing_key` (not error).
- HTTP 409 OR response body containing `"already"` → `already_present` (not error, not re-POST).
- HTTP 2xx → `applied`.
- Anything else → `error` with truncated body in `detail`.

The CLI exit codes are stable across versions — don't break this mapping:

| Code | Meaning |
|---|---|
| 0 | ok |
| 2 | OmniRoute unreachable / registry fetch failed |
| 3 | apply_config completed but some providers errored |
| 4 | `[client]` extra missing (smoke-test only) |
| 5 | smoke-test exception during the chat completion call |
| 6 | `destroy` invoked without `--yes` |

### Auth headers
Every outbound call to OmniRoute (in `bootstrap.py` AND `registry.py`) uses `_bearer_headers()` — reads `OMNIROUTE_API_TOKEN`, omits the header entirely if blank. Don't introduce a parallel auth path.

### Routing strategy (per-provider)
`ProviderEntry.routing_strategy` is optional and passes through to OmniRoute as `providerSpecificData.routingStrategy`. Valid values match OmniRoute's combo strategies: `priority` | `weighted` | `round-robin` | `random` | `least-used` | `cost-optimized`. All six are sequential-fallback variants — OmniRoute does NOT support parallel/scatter-gather routing (`open-sse/services/combo.ts:920` is a single sequential `for` loop). If you find yourself wanting fan-out, build it client-side via `asyncio.gather` over multiple `openai_for_omniroute()` calls — don't try to add it server-side.

### Auth headers
Every outbound call to OmniRoute uses `_bearer_headers()` — reads `OMNIROUTE_API_TOKEN`, omits the header entirely if blank. Don't introduce a parallel auth path.

## Conventions specific to this repo

- **`from __future__ import annotations` is mandatory** at the top of every `.py`. PEP 604 syntax (`str | None`) is used throughout despite the `>=3.11` floor — keep it consistent.
- **Pydantic v2** for all data crossing boundaries (catalog YAML, REST payloads, public return types). Models that hold `model_*` field names use `ConfigDict(protected_namespaces=())` to opt out of Pydantic's protected `model_` namespace — `_NO_PROTECTED_NS` is the local alias.
- **`httpx.AsyncClient` only.** No `requests`, no sync `httpx.Client`. Tests mock with `respx`.
- **Tests against mocked OmniRoute** (`@respx.mock` + `monkeypatch` for env). Never start a real OmniRoute in unit tests.
- **CLI subcommand pattern** — every subcommand sets `func=` + `async_=True|False` on the parser; `main()` dispatches via `asyncio.run` only when `async_=True`. Add new subcommands the same way.
- **Provider ids stay lowercase-kebab** matching upstream (`brave-search`, not `braveSearch`).

## Editing the catalog

`omni_route_config/free-providers.yaml` lives **inside** the package directory (not at repo root) so `setuptools.package-data` (`["py.typed", "*.yaml"]`) actually ships it in the wheel. When adding a provider:
1. Confirm the `provider` id exists in OmniRoute upstream. Cross-check via `omniroutectl sync` against a running instance (it'll list `in_yaml_only` providers as stale).
2. Pick a `priority` that fits the existing bands (10s = top-tier free, 40-90 = generalist/specialist, 100s = search, 200+ = paid fallback). Don't collide with existing values.
3. Add the env-var name to `.env.example` in the matching section.
4. If the provider has unusual config, use `provider_specific_data` — it passes through to OmniRoute as `providerSpecificData`.
5. The `name` field was REMOVED in v0.2 — OmniRoute returns provider names from `/api/v1/models` and `/api/providers` at runtime. Don't re-add it.

Tests in `test_catalog.py::test_bundled_catalog_has_expected_high_priority_providers` lock `groq`, `gemini`, `cerebras`, `openrouter` as required. If you remove one, update the test deliberately.

## Live registry vs YAML catalog

Two sources of truth, on purpose:
- **YAML catalog** (`omni_route_config/free-providers.yaml`) — what the operator wants OmniRoute configured with: env-var mapping, priority preference, aliases, optional default model, enabled flag. This is the curated subset the user intends to push.
- **Registry** (fetched via `registry.fetch_registry()` from a running OmniRoute) — what OmniRoute actually exposes: full provider+model list with modality classification, pulled live from `/api/v1/models` + `/api/providers`.

`omniroutectl sync` reconciles the two. `omniroutectl models` queries the registry and groups by provider + modality (`chat | embedding | image | audio | rerank | moderation | video | music`). Cache lives at `.omniroute/registry.json`, 24h TTL, gitignored.

## What this repo is NOT

- Not a router. OmniRoute owns model selection, fallback, MCP, OAuth flows.
- Not the place to manage OmniRoute's own ~38 env vars (JWT secrets, SQLite path, OAuth client secrets). Those belong in OmniRoute's `.env.example`. We only handle provider-key wiring.
- Not a long-running service. Every CLI invocation is a one-shot; the only persistent state is `.omniroute/pid` (gitignored).
