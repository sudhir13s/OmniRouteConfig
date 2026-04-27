# Changelog

All notable changes to OmniRouteConfig.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

OmniRouteConfig is consumed via Git URL (no PyPI). Pin to a tag in your `pyproject.toml`:

```toml
[project]
dependencies = [
  "OmniRouteConfig @ git+ssh://git@github.com/sudhir13s/OmniRouteConfig.git@v0.2.0",
]
```

---

## [0.2.0] — 2026-04-27

### Added
- **`omniroutectl models`** — list every model OmniRoute exposes, grouped by provider then modality (`chat` / `embedding` / `image` / `audio` / `rerank` / `moderation` / `video` / `music`). Filters: `--type T`, `--provider P`. Pulls live from `/api/v1/models` + `/api/providers`, caches the joined result at `.omniroute/registry.json` for 24h. `--no-cache` forces a refresh.
- **`omniroutectl sync`** — diff the local YAML catalog against OmniRoute's live registry. Reports `in_yaml_only` (stale rows), `in_remote_only` (providers OmniRoute exposes that the YAML doesn't list), and `matched`. `--write` appends new rows for `in_remote_only` providers with a guessed env_var (`UPPERCASE_PROVIDER_ID_API_KEY`) at priority 500, leaving curation to the operator.
- **`omni_route_config.registry` module** — public API: `fetch_registry()`, `get_registry()` (cache-first), `load_cached()`, `save_cache()`. Returns a typed `ProviderRegistry`.
- **New public types** in `omni_route_config.types`: `ModelEntry`, `ProviderRegistry`, `ModelType` (literal of the 8 modalities), `SyncDiff`. Re-exported from the package root.
- **`routing_strategy` field** on `ProviderEntry`. Optional, pass-through to OmniRoute as `providerSpecificData.routingStrategy`. Values match OmniRoute's combo strategies: `priority`, `weighted`, `round-robin`, `random`, `least-used`, `cost-optimized`. All six are sequential-fallback by upstream design — OmniRoute does NOT do parallel/scatter-gather routing (verified against `open-sse/services/combo.ts:920`).
- **CHANGELOG.md** (this file).
- **README "Use as a dependency from another project" section** — concrete `pyproject.toml`, `requirements.txt`, `uv add`, `poetry add`, plus HTTPS-fallback snippets.
- **CLI test coverage** for the eight subcommands that previously lacked it: `init`, `configure`, `down`, `destroy`, `env-sync`, `doctor`, `up`, `smoke-test`. +13 cases.
- **Registry test suite** (`test_registry.py`) — 13 cases covering modality classification, capability round-trip, invalid-row drop, providers with no models, HTTP error propagation, cache TTL, corrupt-JSON tolerance, no-cache flag, bearer header.
- **Models/sync CLI tests** — 9 cases covering filters, dry-run diff, `--write` append, no-op when registry matches, fetch-error rc=2.

### Changed
- **`name` field removed from `ProviderEntry`** (BREAKING). OmniRoute returns provider+model names authoritatively via `/api/v1/models` and `/api/providers`; storing them in the YAML duplicated source-of-truth and went stale when upstream renamed providers. POST payload now sends the provider id (e.g. `"groq"`) as the connection name — same value previously used as the fallback when `name` was absent. The bundled `free-providers.yaml` had its 21 obsolete `name:` lines stripped in the same commit.
- **Bundled YAML moved** from `<repo>/config/free-providers.yaml` to `omni_route_config/free-providers.yaml`. The previous path lived OUTSIDE the Python package and `[tool.setuptools.package-data]` didn't ship it; consumers who `pip install`-ed got a working CLI but `load_catalog()` would crash because the YAML wasn't in the wheel. Now it's inside the package; resolves correctly in dev and from a pip install. `package-data` glob updated to `["py.typed", "*.yaml"]`.
- **`DEFAULT_CATALOG_PATH`** is now resolved via `Path(__file__).resolve().parent / "free-providers.yaml"` instead of climbing to a repo root that doesn't exist outside dev checkouts.
- **`omni_route_config.cli`** docstring + parser registration grew two new subcommands (`models`, `sync`); existing 11 subcommands unchanged.
- **`__init__.py`** public surface expanded to 13 symbols.

### Fixed
- **YAML packaging bug** (#9) — see Changed above. Surfaced when an external consumer tried to install via `pip install "OmniRouteConfig @ git+ssh://...@v0.1.0"` and got `FileNotFoundError` on every catalog operation.

### Deferred / cancelled
- **v0.2 OAuth provider helpers** (Cursor / Claude Code / Codex device-flow) — cancelled. Out of scope. Upstream OmniRoute's OAuth surface area isn't stable enough to wrap.
- **Scatter-gather routing** — verified upstream is sequential-only by design. Not implemented here either. If a use case appears (latency race for chat, ensemble for STT comparison), build it client-side via `asyncio.gather`.

---

## [0.1.0] — 2026-04-26

### Added
- Initial release. Imports the prior `freellm` skeleton, renames the package to `OmniRouteConfig` (Python module: `omni_route_config`).
- `omniroutectl` CLI with 11 subcommands: `up`, `down`, `destroy`, `doctor`, `env-sync`, `init`, `configure`, `status`, `smoke-test`, `catalog`, `version`.
- Curated catalog of 21 free-tier providers in `config/free-providers.yaml` (LLM, search, STT/TTS, paid fallback). `aliases:` field per entry to map alternate shell-env-var names (e.g. `CLAUDE_CONSOLE_API_KEY` → `ANTHROPIC_API_KEY`).
- `.env` lifecycle: read shell env → fill blanks → generate missing OmniRoute server secrets (`JWT_SECRET`, `API_KEY_SECRET`, `STORAGE_ENCRYPTION_KEY`, `MACHINE_ID_SALT`) → write atomically with `0600` perms.
- Docker lifecycle: persistent named volume `omniroute-data`, named container `omniroute`, restart policy `unless-stopped`. `down` stops, `destroy --yes` removes the volume.
- Pydantic v2 models for catalog and REST contract.
- Initial test suite (33 cases) using `respx` to mock OmniRoute.
- CI on GitHub Actions across Python 3.11, 3.12, 3.13.
