# OmniRouteConfig

> One CLI to bootstrap [OmniRoute](https://github.com/sudhir13s/OmniRoute) from your shell. Reads provider keys from `os.environ`, generates server secrets, runs the Docker image with a persistent volume, pushes the curated free-tier catalog. Idempotent. Reversible.

[![status](https://img.shields.io/badge/status-alpha-yellow)](#status) ![python](https://img.shields.io/badge/python-3.11%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green)

---

## What this is

OmniRoute is a Node.js LLM-router. It exposes a dashboard, an OpenAI-compatible `/api/v1` proxy, and a REST management API. Configuring it manually for every fresh deploy is repetitive — paste keys in the dashboard, set priorities, click save. This package replaces that with one command:

```bash
omniroutectl up
```

Which:

1. Reads provider API keys from your shell (`GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, …).
2. Generates OmniRoute server secrets (`JWT_SECRET`, `API_KEY_SECRET`, `STORAGE_ENCRYPTION_KEY`, `MACHINE_ID_SALT`) on first run, persists them in `.env` so they stay stable across restarts.
3. `docker run` OmniRoute with `--env-file .env` and a persistent named volume.
4. Waits for the dashboard to come up.
5. POSTs every catalog row whose API key is set to OmniRoute's `/api/providers`.

This package owns **declarative config + Python ergonomics**. OmniRoute owns the routing chain, fallback, OAuth flows, MCP server, dashboard.

---

## Status

`v0.1` — alpha. Verified against `diegosouzapw/omniroute:3.7.x`.

Ships:

- ✅ `omniroutectl` CLI: `up`, `down`, `destroy`, `doctor`, `env-sync`, `models`, `sync`, plus the originals (`init`, `configure`, `status`, `smoke-test`, `catalog`, `version`) — 12 subcommands total.
- ✅ Curated catalog (`config/free-providers.yaml`) — 21 providers across free-tier LLM, search, STT/TTS, paid fallback. `aliases:` field per entry so a shell var named `CLAUDE_CONSOLE_API_KEY` is recognized as `ANTHROPIC_API_KEY`.
- ✅ `.env` lifecycle: read shell env → fill blanks → generate missing secrets → write atomically with `0600` perms.
- ✅ Docker lifecycle: persistent volume `omniroute-data`, named container `omniroute`, restart policy `unless-stopped`. `down` stops, `destroy` removes the volume (data loss — prompts to confirm).
- ✅ Pydantic-validated catalog and REST contract.
- ✅ Live registry: `models` lists models by provider + modality, `sync` reconciles YAML vs OmniRoute's live `/api/v1/models` response. 24h disk cache at `.omniroute/registry.json`.
- ✅ Tests: 68 passing, mocked OmniRoute via `respx`.

Roadmap:

- `v0.4` — TBD.

---

## Install

```bash
# Editable install (recommended while v0.1)
git clone git@github.com:sudhir13s/OmniRouteConfig.git
cd OmniRouteConfig
pip install -e ".[dev,client]"

# Or pip-install once published
pip install "OmniRouteConfig @ git+ssh://git@github.com/sudhir13s/OmniRouteConfig.git@main"
```

The Python import name stays lowercase per PEP 8: `from omni_route_config import bootstrap, client`.

Prerequisites: Python 3.11+ and Docker. (`scripts/setup.sh` checks both.)

---

## Quickstart (the only commands you need)

```bash
# 1. Spin up
omniroutectl up
#   ↳ writes .env, runs Docker, applies catalog
#     output shows: keys-from-shell, secrets-generated, apply summary

# 2. First time: open the dashboard, sign up for an admin account.
#    Set the admin password to whatever you want — this is YOUR password,
#    not auto-generated.
open http://localhost:20128

# 3. Dashboard → API Keys → create a management token. Paste into .env:
#    OMNIROUTE_API_TOKEN=<paste here>

# 4. Re-apply the catalog now that the API is authenticated.
omniroutectl configure

# 5. Audit any time
omniroutectl doctor
omniroutectl status

# 6. Stop (volume preserved — data persists)
omniroutectl down

# 7. Stop AND remove the volume (DESTROYS admin + connections)
omniroutectl destroy --yes
```

Step 3 is one-time. Subsequent restarts just need `omniroutectl up`.

---

## Why two re-applies?

OmniRoute v3.7+ requires a management token for any write. On a fresh container the dashboard is unauthenticated, so step 1 lands here:

```text
"apply": { "applied": 0, "skipped_missing_key": 17, "errors": 4 }
                                                    ^^^^^^^^^
                                                    HTTP 401 — auth gate
```

After step 3 (admin token in `.env`), step 4 re-runs the apply with the token in the `Authorization: Bearer ...` header and lands here:

```text
"apply": { "applied": 4, "skipped_missing_key": 17, "errors": 0 }
```

The 17 are catalog entries you have no key for — those are silently skipped, never errors.

---

## Subcommand reference

| Command | What it does |
|---|---|
| `omniroutectl up` | env-sync → docker run with `--env-file` → wait ready → apply catalog |
| `omniroutectl down` | Stop + remove the container. **Volume preserved.** |
| `omniroutectl destroy --yes` | `down` + remove the persistent volume. **DESTRUCTIVE.** |
| `omniroutectl env-sync` | Read shell + existing .env → generate missing secrets → write merged .env |
| `omniroutectl doctor` | Audit: which provider keys are present, container state, .env health |
| `omniroutectl models [--type TYPE] [--provider P] [--no-cache]` | Fetch live model list from OmniRoute, grouped by provider + modality. JSON output. 24h cache. |
| `omniroutectl sync [--path P] [--write] [--no-cache]` | Diff local YAML catalog vs OmniRoute's live registry. `--write` appends missing providers. |
| `omniroutectl init` | Just start OmniRoute (no env-sync, no apply) |
| `omniroutectl configure` | Just push the catalog to a running OmniRoute |
| `omniroutectl status` | Reachability + how many providers OmniRoute has configured |
| `omniroutectl smoke-test` | Send a chat completion through `/api/v1` (requires `[client]` extra) |
| `omniroutectl catalog` | Print the parsed catalog (validates the YAML) |
| `omniroutectl version` | Print package version |

Only `omniroutectl` is installed. The legacy `omni-route-config` script alias was dropped in the rename.

---

## How the `.env` is built

`omniroutectl env-sync` (and `up`, which calls it first) merges three sources, **highest priority first**:

1. **Existing `.env`** — never overwritten. Your `INITIAL_PASSWORD=123456`, your custom `JWT_SECRET`, your hand-edited fields all stay.
2. **Shell env** — fills any blank slot. `os.environ["GROQ_API_KEY"]` → `GROQ_API_KEY=` line. Catalog `aliases:` are honored: if `ANTHROPIC_API_KEY` is empty but `CLAUDE_CONSOLE_API_KEY` is set, the alias's value lands in the canonical slot.
3. **Generated defaults** — `JWT_SECRET`, `API_KEY_SECRET`, `STORAGE_ENCRYPTION_KEY`, `MACHINE_ID_SALT` are generated on first run only and written. Re-runs preserve them so OmniRoute admin sessions survive container restarts.

**`INITIAL_PASSWORD` is never auto-generated.** It only matters when OmniRoute first boots against an empty volume; you set the real admin password by typing it into the dashboard signup form, not via env. Surfaced as a blank slot for visibility.

`.env` is written with `0600` permissions (best-effort).

---

## How `up` runs Docker

```bash
docker run -d \
  --name omniroute \
  --restart unless-stopped \
  -p 20128:20128 \
  -v omniroute-data:/app/data \
  --env-file .env \
  diegosouzapw/omniroute:latest
```

Override defaults via env vars:

```bash
OMNIROUTE_CONTAINER=omni-prod \
OMNIROUTE_IMAGE=omniroute:full \
OMNIROUTE_VOLUME=omniroute-data-prod \
OMNIROUTE_PORT=20130 \
omniroutectl up
```

`OMNIROUTE_IMAGE=omniroute:full` is the natural override if you build your own from the [OmniRoute fork](https://github.com/sudhir13s/OmniRoute) (`docker compose --profile full up -d --build`).

---

## Catalog (`config/free-providers.yaml`)

```yaml
providers:
  - provider: groq                     # OmniRoute provider id (must match upstream)
    env_var: GROQ_API_KEY              # env var holding the API key
    priority: 10                       # lower = higher priority in OmniRoute's chain
    default_model: llama-3.3-70b-versatile
    routing_strategy: priority         # optional; default is OmniRoute's instance-wide priority strategy

  - provider: anthropic
    env_var: ANTHROPIC_API_KEY
    aliases:                           # alternate names env_sync also accepts
      - CLAUDE_CONSOLE_API_KEY
    priority: 200
    note: paid fallback — only routed if free options exhaust
```

Adding a row:
1. Confirm the `provider` id exists in the OmniRoute upstream registry (`src/shared/constants/providers.ts`). If it doesn't, POST returns `400 Invalid provider`.
2. Pick a `priority` matching the existing bands (10s = top free, 40-90 = generalist/specialist, 100s = search, 200+ = paid fallback). Don't collide with existing.
3. Add the env var to `.env.example` so users know what to set.

---

## Discovering models (live registry)

Once OmniRoute is running, `models` and `sync` let you inspect what's actually available vs what the local catalog declares.

```bash
omniroutectl models                           # all providers, all modalities (JSON)
omniroutectl models --type audio              # only audio models (STT/TTS)
omniroutectl models --provider groq           # only groq's models
omniroutectl models --no-cache                # force live fetch, skip 24h disk cache

omniroutectl sync                             # dry-run: diff YAML vs live registry
omniroutectl sync --write                     # append in_remote_only providers to local YAML
```

`sync` output groups providers into three buckets:
- `in_yaml_only` — in your local catalog but not in OmniRoute's `/api/v1/models`. Likely stale.
- `in_remote_only` — OmniRoute knows about them but your YAML has no entry. `--write` appends these with a guessed `env_var` and `priority: 500`.
- `matched` — present in both. Healthy.

Modality taxonomy sourced from OmniRoute's `/api/v1/models`: `chat`, `embedding`, `image`, `audio`, `rerank`, `moderation`, `video`, `music`.

The registry module is also importable: `from omni_route_config.registry import get_registry`.

---

## Programmatic use

```python
import asyncio
from omni_route_config import bootstrap, client

async def main():
    await bootstrap.ensure_running(port=20128)        # idempotent
    summary = await bootstrap.apply_config()          # reads .env, POSTs catalog
    print(f"applied={summary.applied} skipped={summary.skipped_missing_key}")

    c = client.openai_for_omniroute()                 # OpenAI SDK pre-pointed at proxy
    resp = c.chat.completions.create(
        model="auto",                                  # let OmniRoute pick
        messages=[{"role": "user", "content": "Say hi"}],
    )
    print(resp.choices[0].message.content)

asyncio.run(main())
```

---

## What this is NOT

- Not a router. OmniRoute owns model selection, fallback, MCP, OAuth flows.
- Not a parallel/scatter-gather router. OmniRoute is sequential-fallback by design (verified upstream). All 6 routing strategies — `priority`, `weighted`, `round-robin`, `random`, `least-used`, `cost-optimized` — execute providers one at a time.
- Not a manager for OmniRoute's full ~38 server-side env vars. Anything in `.env` is passed through Docker via `--env-file`, but only the fields documented in `.env.example` are owned by `env_sync`. Add more rows freely; they pass through.
- Not a long-running service. Every CLI invocation is one-shot. The persistent state lives in:
  - `.env` (your secrets + provider keys)
  - Docker volume `omniroute-data` (OmniRoute's SQLite DB, admin accounts, provider connections)
  - `.omniroute/` (only if you used the npx fallback — Docker doesn't write here)

---

## License

MIT.
