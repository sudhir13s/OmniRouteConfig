# omni-route-config

> Bootstrap + auto-configure [OmniRoute](https://github.com/sudhir13s/OmniRoute) for **$0-spend AI routing**. Idempotent Python scripts, env-var conventions, and curated free-tier provider configs. Drop-in setup layer for any project that wants to ship with OmniRoute pre-wired.

[![status](https://img.shields.io/badge/status-alpha-yellow)](#status) ![python](https://img.shields.io/badge/python-3.11%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green)

---

## What this is (and isn't)

**Is**: a configuration + bootstrap layer that sits on top of OmniRoute. Reads a curated YAML catalog of free-tier providers, reads matching API keys from your environment, and POSTs them to a running OmniRoute instance via `/api/providers`. Plus a thin Python OpenAI-SDK wrapper that talks to OmniRoute's `/api/v1/*` endpoints.

**Isn't**: an LLM router. OmniRoute *is* the router. This package does no inference, owns no quota state, makes no model decisions. It's a **config supplier + lifecycle helper**.

```
your project (Python)
    │
    ├── from omni_route_config import bootstrap, client
    │
    ├── bootstrap.ensure_running()          # installs OmniRoute if missing, starts it on :20128
    ├── bootstrap.apply_config()            # reads config/free-providers.yaml + env vars
    │                                       #   POSTs each enabled provider to OmniRoute
    │
    └── c = client.openai_for_omniroute()   # OpenAI SDK pointed at http://localhost:20128/api/v1
        c.chat.completions.create(model="auto", messages=[...])
                                            # → routes through OmniRoute → free providers → response
```

OmniRoute owns the routing chain, fallback, OAuth flows, MCP server, dashboard. This package owns the **declarative config + Python ergonomics**.

---

## Status

`v0.1` — alpha. Ships:

- ✅ Curated provider catalog (`config/free-providers.yaml`) — declarative list of free-tier providers, the env vars OmniRoute expects per provider, default priorities, optional model preferences.
- ✅ `omni_route_config.bootstrap` — `ensure_running()` (installs via `npx omniroute` or docker, waits for ready), `apply_config()` (POSTs catalog → OmniRoute REST API), `tear_down()`.
- ✅ `omni_route_config.client` — `openai_for_omniroute()` returns a configured `openai.OpenAI` instance pointed at the local OmniRoute proxy.
- ✅ `omni-route-config` CLI: `init | configure | status | smoke-test | down`.
- ✅ Pydantic-validated catalog shape; OmniRoute REST contract typed.
- ✅ Tests against mocked OmniRoute (`respx`).

Roadmap:

- `v0.2` — OAuth provider helpers (Cursor / Claude Code / Codex device-flow trigger).
- `v0.3` — Catalog auto-update from OmniRoute's own `/api/v1/models` (single source of truth).
- `v0.4` — `omni-route-config doctor` health probe + repair.

---

## Install

```bash
# As a library in your project
pip install "omni-route-config @ git+ssh://git@github.com/sudhir13s/omni-route-config.git@main"

# Or editable / local
git clone git@github.com:sudhir13s/omni-route-config.git
cd omni-route-config
pip install -e ".[dev,client]"
```

OmniRoute itself ships separately. See [scripts/setup.sh](./scripts/setup.sh) for one-shot install (Node 20+, npm, optional Docker).

---

## Quickstart

```python
import asyncio
from omni_route_config import bootstrap, client

async def main():
    # 1. Make sure OmniRoute is running on localhost:20128.
    #    Installs via `npx omniroute@latest` if not present.
    await bootstrap.ensure_running(port=20128)

    # 2. Read config/free-providers.yaml + your env vars,
    #    POST each enabled provider to OmniRoute /api/providers.
    summary = await bootstrap.apply_config()
    print(f"Configured {summary.applied}/{summary.total} providers")

    # 3. Use the OpenAI SDK pointed at OmniRoute.
    c = client.openai_for_omniroute()
    resp = c.chat.completions.create(
        model="auto",                      # "auto" lets OmniRoute pick the chain
        messages=[{"role": "user", "content": "Summarize: ..."}],
    )
    print(resp.choices[0].message.content)

asyncio.run(main())
```

CLI equivalent:

```bash
omni-route-config init                    # install + start OmniRoute (idempotent)
omni-route-config configure               # POST config/free-providers.yaml -> OmniRoute
omni-route-config status                  # show running state + which providers are wired
omni-route-config smoke-test              # send a dummy chat completion through the chain
omni-route-config down                    # stop OmniRoute (keeps SQLite state)
```

---

## Catalog shape (`config/free-providers.yaml`)

```yaml
# Each entry maps a free-tier provider that OmniRoute supports natively.
# `provider` MUST match an OmniRoute provider id (see OmniRoute README).
# `env_var` names the env var omni-route-config reads to find the API key.
# `priority` (lower = higher priority) is passed to OmniRoute on POST.

providers:
  - provider: groq
    env_var: GROQ_API_KEY
    priority: 10
    name: Groq (Llama 3.3 70B + Mixtral)
    default_model: llama-3.3-70b-versatile

  - provider: gemini
    env_var: GEMINI_API_KEY
    priority: 20
    name: Gemini Free Tier
    default_model: gemini-2.0-flash-exp

  - provider: cerebras
    env_var: CEREBRAS_API_KEY
    priority: 30

  - provider: openrouter
    env_var: OPENROUTER_API_KEY
    priority: 40
    note: Free :free-suffixed models only.
```

Providers with missing env vars are silently skipped (logged once at startup). No POST happens for them — OmniRoute simply doesn't know about them, and falls through to whichever IS configured.

---

## Env vars

omni-route-config itself reads:

| Var | Purpose | Default |
|---|---|---|
| `OMNIROUTE_URL` | OmniRoute base URL | `http://localhost:20128` |
| `OMNIROUTE_PORT` | port if we're starting the service ourselves | `20128` |
| `OMNIROUTE_API_TOKEN` | optional bearer token for OmniRoute admin API | none |
| `OMNI_ROUTE_CONFIG_PATH` | override path to `free-providers.yaml` | bundled default |

Plus all the provider keys named in your catalog (e.g. `GROQ_API_KEY`, `GEMINI_API_KEY`, …). See `config/free-providers.yaml` for the full list.

OmniRoute itself reads ~38 of its own env vars (OAuth client secrets, JWT secrets, SQLite path, ...). We do NOT manage those — see OmniRoute's `.env.example`. omni-route-config only handles the *provider-key* layer.

---

## Why a separate package

OmniRoute is a Next.js + Express app with a dashboard and a SQLite DB. Configuring it manually for every fresh deploy is repetitive: click through the dashboard, paste keys, set priorities. omni-route-config replaces that clicking with `omni-route-config configure` reading a committed YAML + env-var keys.

This is config-as-code on top of OmniRoute, nothing more.

---

## License

MIT.
