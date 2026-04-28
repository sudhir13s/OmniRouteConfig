# OmniRouteConfig

> One CLI to bootstrap [OmniRoute](https://github.com/sudhir13s/OmniRoute) from your shell. Reads provider keys from `os.environ`, generates server secrets, runs the Docker image with a persistent volume, pushes the curated free-tier catalog. Idempotent. Reversible.

[![status](https://img.shields.io/badge/status-alpha-yellow)](#status) ![python](https://img.shields.io/badge/python-3.11%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green)

OmniRoute is a separate Node.js LLM-router (dashboard + OpenAI-compatible `/api/v1` proxy + REST management API). This package owns **declarative config + Python ergonomics**; OmniRoute owns the routing chain, fallback, OAuth flows, MCP server, dashboard.

---

## Status

`v0.2.0` — alpha. Verified against `diegosouzapw/omniroute:3.7.x`. 68 tests passing on Python 3.11 / 3.12 / 3.13.

Ships:

- ✅ `omniroutectl` CLI — 13 subcommands (see [reference](#subcommand-reference)).
- ✅ Curated catalog (`omni_route_config/free-providers.yaml`, shipped inside the package) — 21 providers across LLM / search / STT-TTS / paid fallback. `aliases:` field maps alternate shell-var names (e.g. `CLAUDE_CONSOLE_API_KEY` → `ANTHROPIC_API_KEY`).
- ✅ `.env` lifecycle — read shell env, fill blanks, generate missing OmniRoute server secrets (`JWT_SECRET`, `API_KEY_SECRET`, `STORAGE_ENCRYPTION_KEY`, `MACHINE_ID_SALT`), atomic write with `0600` perms.
- ✅ Docker lifecycle — persistent volume `omniroute-data`, container `omniroute`, restart policy `unless-stopped`. `down` stops, `destroy --yes` removes the volume.
- ✅ Live registry — `models` / `sync` query OmniRoute's `/api/v1/models` + `/api/providers`, classify by modality, cache 24h at `.omniroute/registry.json`.

---

## Install

```bash
# Editable (working on this repo)
git clone git@github.com:sudhir13s/OmniRouteConfig.git
cd OmniRouteConfig
pip install -e ".[dev,client]"

# One-shot (just want the CLI)
pip install "OmniRouteConfig @ git+ssh://git@github.com/sudhir13s/OmniRouteConfig.git@v0.2.0"
```

Prerequisites: Python 3.11+, Docker. (`scripts/setup.sh` checks both.) Python import name is lowercase: `from omni_route_config import bootstrap, client`.

---

## Use as a dependency from another project

OmniRouteConfig is **not on PyPI**. Consumers pull from this Git repo, pinned to a tag (`v0.2.0`) or `main`.

```toml
# pyproject.toml
[project]
dependencies = [
  "OmniRouteConfig @ git+ssh://git@github.com/sudhir13s/OmniRouteConfig.git@v0.2.0",
]

# include the OpenAI-SDK adapter
[project.optional-dependencies]
ai = ["OmniRouteConfig[client] @ git+ssh://git@github.com/sudhir13s/OmniRouteConfig.git@v0.2.0"]
```

```bash
# uv
uv add "git+ssh://git@github.com/sudhir13s/OmniRouteConfig.git@v0.2.0"

# poetry
poetry add "git+ssh://git@github.com/sudhir13s/OmniRouteConfig.git#v0.2.0"
```

Use `git+https://github.com/...` instead of `git+ssh://git@github.com/...` if your CI lacks SSH keys. Pin to a commit SHA (`@7bdce4d`) for full reproducibility, or `@main` to track tip.

After install, the CLI lands on `$PATH` and these symbols are importable:

```python
from omni_route_config import (
    bootstrap, client, registry, load_catalog,
    ProviderEntry, ProviderCatalog, ApplyResult, OmniRouteStatus,
    ModelEntry, ProviderRegistry, ModelType, SyncDiff,
)
```

---

## Quickstart

```bash
omniroutectl up                          # writes .env, runs Docker, applies catalog
open http://localhost:20128              # sign up admin (set your password here, not via env)
# Dashboard → API Keys → create a token. Paste into .env: OMNIROUTE_API_TOKEN=<token>
omniroutectl configure                   # re-apply with auth — applied count goes up
omniroutectl doctor                      # audit anytime
omniroutectl down                        # stop (volume preserved)
omniroutectl destroy --yes               # stop + delete volume (DESTROYS admin + connections)
```

Two-stage apply is intentional: OmniRoute v3.7+ requires a token for any write, and the token only exists after the admin signs up on the dashboard. First `up` applies whatever doesn't need auth (= nothing on a fresh container, all errors land as HTTP 401); after the token is in `.env`, `configure` re-applies cleanly. Subsequent restarts just need `omniroutectl up`.

---

## Subcommand reference

| Command | Purpose |
|---|---|
| `up` | env-sync → docker run with `--env-file` → wait ready → apply catalog |
| `down` | Stop + remove the container. Volume preserved. |
| `destroy --yes` | `down` + remove the persistent volume. **Destructive.** |
| `env-sync [--path P]` | Read shell + existing .env → generate missing secrets → write merged .env |
| `doctor [--path P]` | Audit: provider keys present, container state, .env health |
| `models [--type T] [--provider P] [--no-cache]` | Live model list grouped by provider + modality. JSON. 24h cache. |
| `sync [--path P] [--write] [--no-cache]` | Diff local YAML vs live registry. `--write` appends `in_remote_only` rows. |
| `init` | Just start OmniRoute |
| `configure [--path P]` | Just push the catalog to a running OmniRoute |
| `status` | Reachability + provider count |
| `smoke-test` | Send a chat completion through `/api/v1` (requires `[client]` extra) |
| `catalog [--path P]` | Print the parsed catalog (validates the YAML) |
| `version` | Print package version |

Exit codes (stable across versions): `0` ok, `2` unreachable / fetch failed, `3` apply errors, `4` `[client]` extra missing, `5` smoke-test exception, `6` `destroy` without `--yes`.

---

## Catalog format

```yaml
providers:
  - provider: groq                       # OmniRoute provider id (must match upstream)
    env_var: GROQ_API_KEY                # env var holding the API key
    priority: 10                         # lower = higher in OmniRoute's chain
    default_model: llama-3.3-70b-versatile
    routing_strategy: priority           # optional: priority|weighted|round-robin|random|least-used|cost-optimized

  - provider: anthropic
    env_var: ANTHROPIC_API_KEY
    aliases: [CLAUDE_CONSOLE_API_KEY]    # alternates env_sync also accepts
    priority: 200
    note: paid fallback — only routed if free options exhaust
```

Priority bands: `10s` top-tier free, `40-90` generalist/specialist, `100s` search, `200+` paid fallback. Don't collide. The `provider` id must exist in OmniRoute's upstream registry (`src/shared/constants/providers.ts`) — `omniroutectl sync` will flag stale or missing rows against a live instance.

---

## Live registry

```bash
omniroutectl models                      # all providers, all modalities
omniroutectl models --type audio         # filter by modality
omniroutectl models --provider groq      # filter by provider
omniroutectl sync                        # dry-run diff
omniroutectl sync --write                # append in_remote_only providers to YAML
```

`sync` buckets each provider into `matched` (healthy), `in_yaml_only` (stale — drop or update), or `in_remote_only` (auto-append with `--write`).

Modalities pulled from OmniRoute's `/api/v1/models`: `chat`, `embedding`, `image`, `audio`, `rerank`, `moderation`, `video`, `music`.

Importable: `from omni_route_config.registry import get_registry`.

---

## Programmatic use

```python
import asyncio
from omni_route_config import bootstrap, client

async def main():
    await bootstrap.ensure_running(port=20128)
    summary = await bootstrap.apply_config()
    print(f"applied={summary.applied} skipped={summary.skipped_missing_key}")

    c = client.openai_for_omniroute()
    resp = c.chat.completions.create(
        model="auto",
        messages=[{"role": "user", "content": "Say hi"}],
    )
    print(resp.choices[0].message.content)

asyncio.run(main())
```

---

## Docker overrides

Defaults: container `omniroute`, image `diegosouzapw/omniroute:latest`, volume `omniroute-data`, port `20128`. Override via env vars:

```bash
OMNIROUTE_CONTAINER=omni-prod OMNIROUTE_IMAGE=omniroute:full \
OMNIROUTE_VOLUME=omniroute-data-prod OMNIROUTE_PORT=20130 \
omniroutectl up
```

Use `OMNIROUTE_IMAGE=omniroute:full` if you build your own from the [OmniRoute fork](https://github.com/sudhir13s/OmniRoute) (`docker compose --profile full up -d --build`).

---

## What this is NOT

- Not a router. OmniRoute owns model selection, fallback, MCP, OAuth.
- Not parallel/scatter-gather. All 6 routing strategies are sequential-fallback by upstream design.
- Not a manager for OmniRoute's full ~38 server env vars. Pass-through via `--env-file`; only fields in `.env.example` are owned by `env_sync`.
- Not a long-running service. One-shot CLI. Persistent state lives in `.env`, Docker volume `omniroute-data`, and `.omniroute/` (npx PID + registry cache).

See [CHANGELOG.md](CHANGELOG.md) for release notes.

---

## License

MIT.
