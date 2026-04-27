"""CLI entry: `python -m omni_route_config <subcommand>` or `omniroutectl <subcommand>`.

Subcommands:
  up           One-shot: env-sync + docker run --env-file .env + apply catalog.
  down         Stop the docker container (or npx process). Volume preserved.
  destroy      `down` + remove persistent docker volume. PROMPTS for confirmation.
  doctor       Audit: which provider keys are present, container state, .env health.
  env-sync     Read shell env, generate OmniRoute secrets, write merged .env.
  init         Ensure OmniRoute is running (starts via npx/docker if needed).
  configure    Read free-providers.yaml + env vars, POST to OmniRoute /api/providers.
  status       Print whether OmniRoute is reachable + how many providers it has.
  smoke-test   Send a dummy chat completion through the chain (requires `[client]` extra).
  catalog      Print the parsed catalog (validates the YAML).
  version      Print this package version.

The convenience commands (up, down, destroy, doctor, env-sync) wrap the
primitive ones (init, configure, status). All primitives still work
standalone for users who prefer manual control.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from omni_route_config import __version__
from omni_route_config.bootstrap import (
    _docker_container_name,
    _docker_image,
    _docker_inspect_state,
    _docker_volume,
    apply_config,
    destroy_volume,
    ensure_running,
    status,
    tear_down,
)
from omni_route_config.catalog import load_catalog
from omni_route_config.env_sync import SERVER_SECRETS, sync_env_file


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


# ---------- subcommands ----------


def cmd_version(_args: argparse.Namespace) -> int:
    _print({"version": __version__})
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    cat = load_catalog(args.path)
    _print(cat.model_dump())
    return 0


async def _cmd_status(_args: argparse.Namespace) -> int:
    s = await status()
    _print(s.model_dump())
    return 0 if s.reachable else 2


async def _cmd_init(args: argparse.Namespace) -> int:
    s = await ensure_running(port=args.port, timeout_s=args.timeout)
    _print(s.model_dump())
    return 0 if s.reachable else 2


async def _cmd_configure(args: argparse.Namespace) -> int:
    cat = load_catalog(args.path)
    result = await apply_config(cat)
    _print(result.model_dump())
    return 0 if result.errors == 0 else 3


async def _cmd_smoke(args: argparse.Namespace) -> int:
    try:
        from omni_route_config import client  # noqa: F401
        from omni_route_config.client import openai_for_omniroute
    except ImportError as e:
        print(json.dumps({"error": str(e)}))
        return 4
    c = openai_for_omniroute()
    try:
        resp = c.chat.completions.create(
            model=args.model or "auto",
            messages=[{"role": "user", "content": args.prompt}],
            max_tokens=64,
        )
    except Exception as e:
        _print({"error": type(e).__name__, "detail": str(e)})
        return 5
    _print(
        {
            "model": getattr(resp, "model", None),
            "content": resp.choices[0].message.content if resp.choices else None,
            "usage": getattr(resp, "usage", None) and resp.usage.model_dump(),
        }
    )
    return 0


def cmd_down(_args: argparse.Namespace) -> int:
    killed = tear_down()
    _print({"stopped": killed, "container": _docker_container_name()})
    return 0


def cmd_destroy(args: argparse.Namespace) -> int:
    if not args.yes:
        print(
            "ERROR: `destroy` removes the OmniRoute data volume — "
            "admin accounts, provider connections, logs are lost.\n"
            "Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 6
    tear_down()
    removed = destroy_volume()
    _print({"volume_removed": removed, "volume": _docker_volume()})
    return 0


def cmd_env_sync(args: argparse.Namespace) -> int:
    report = sync_env_file(args.path)
    _print(
        {
            "wrote": str(report.path),
            "provider_keys_from_shell": report.provider_keys_from_shell,
            "provider_keys_missing": report.provider_keys_missing,
            "secrets_generated": report.secrets_generated,
            "secrets_preserved": report.secrets_preserved,
            "server_defaults_added": report.server_defaults_added,
        }
    )
    return 0


async def _cmd_doctor(args: argparse.Namespace) -> int:
    cat = load_catalog()
    env_path = Path(args.path).expanduser()
    from omni_route_config.env_sync import parse_dotenv

    dot = parse_dotenv(env_path)
    shell = os.environ
    env_keys = sorted({e.env_var for e in cat.providers})
    keys_in_dotenv = [k for k in env_keys if dot.get(k)]
    keys_in_shell_only = [k for k in env_keys if shell.get(k) and not dot.get(k)]
    keys_missing = [k for k in env_keys if not dot.get(k) and not shell.get(k)]
    missing_secrets = [s for s in SERVER_SECRETS if not dot.get(s)]
    container = _docker_container_name()
    container_state = _docker_inspect_state(container)
    reach = await status()
    _print(
        {
            "dotenv_path": str(env_path),
            "dotenv_exists": env_path.exists(),
            "provider_keys_in_dotenv": keys_in_dotenv,
            "provider_keys_in_shell_only": keys_in_shell_only,
            "provider_keys_missing": keys_missing,
            "server_secrets_missing": missing_secrets,
            "docker": {
                "container": container,
                "image": _docker_image(),
                "volume": _docker_volume(),
                "state": container_state,
            },
            "reachable": reach.reachable,
            "providers_configured": reach.providers_configured,
        }
    )
    return 0 if reach.reachable or container_state == "running" else 2


async def _cmd_up(args: argparse.Namespace) -> int:
    """env-sync → ensure_running → apply_config."""
    report = sync_env_file(args.path)
    s = await ensure_running(port=args.port, timeout_s=args.timeout)
    if not s.reachable:
        _print(
            {
                "stage": "ensure_running",
                "ok": False,
                "status": s.model_dump(),
                "env_sync": {
                    "wrote": str(report.path),
                    "secrets_generated": report.secrets_generated,
                },
            }
        )
        return 2
    cat = load_catalog()
    apply = await apply_config(cat)
    _print(
        {
            "ok": True,
            "env_sync": {
                "wrote": str(report.path),
                "provider_keys_from_shell": report.provider_keys_from_shell,
                "secrets_generated": report.secrets_generated,
            },
            "status": s.model_dump(),
            "apply": {
                "total": apply.total,
                "applied": apply.applied,
                "already_present": apply.already_present,
                "skipped_missing_key": apply.skipped_missing_key,
                "errors": apply.errors,
            },
        }
    )
    return 0 if apply.errors == 0 else 3


# ---------- parser ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omniroutectl",
        description="Configure + bootstrap OmniRoute.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("version", help="Print package version").set_defaults(
        func=cmd_version, async_=False
    )

    p_cat = sub.add_parser("catalog", help="Print the parsed provider catalog")
    p_cat.add_argument("--path", default=None, help="Path to free-providers.yaml")
    p_cat.set_defaults(func=cmd_catalog, async_=False)

    p_status = sub.add_parser("status", help="Show OmniRoute reachability + provider count")
    p_status.set_defaults(func=_cmd_status, async_=True)

    p_init = sub.add_parser("init", help="Ensure OmniRoute is running")
    p_init.add_argument("--port", type=int, default=None)
    p_init.add_argument("--timeout", type=int, default=90, help="Seconds to wait for ready")
    p_init.set_defaults(func=_cmd_init, async_=True)

    p_cfg = sub.add_parser(
        "configure",
        help="POST every runnable provider in the catalog to OmniRoute",
    )
    p_cfg.add_argument("--path", default=None, help="Path to free-providers.yaml")
    p_cfg.set_defaults(func=_cmd_configure, async_=True)

    p_smoke = sub.add_parser(
        "smoke-test",
        help="Send a dummy chat completion through OmniRoute (requires [client] extra)",
    )
    p_smoke.add_argument("--model", default="auto")
    p_smoke.add_argument(
        "--prompt", default="Say 'OmniRouteConfig online' and nothing else."
    )
    p_smoke.set_defaults(func=_cmd_smoke, async_=True)

    sub.add_parser(
        "down", help="Stop OmniRoute container/process. Volume preserved."
    ).set_defaults(func=cmd_down, async_=False)

    p_destroy = sub.add_parser(
        "destroy",
        help="Stop + REMOVE the data volume (all admin/provider data lost).",
    )
    p_destroy.add_argument("--yes", action="store_true", help="Confirm destructive op")
    p_destroy.set_defaults(func=cmd_destroy, async_=False)

    p_env = sub.add_parser(
        "env-sync",
        help="Read shell env, generate OmniRoute secrets, write merged .env",
    )
    p_env.add_argument("--path", default=".env", help="Path to .env (default: ./.env)")
    p_env.set_defaults(func=cmd_env_sync, async_=False)

    p_doctor = sub.add_parser(
        "doctor",
        help="Audit: which keys are present, container state, .env health",
    )
    p_doctor.add_argument("--path", default=".env")
    p_doctor.set_defaults(func=_cmd_doctor, async_=True)

    p_up = sub.add_parser(
        "up",
        help="One-shot: env-sync + start OmniRoute (with .env) + apply catalog",
    )
    p_up.add_argument("--path", default=".env", help="Path to .env (default: ./.env)")
    p_up.add_argument("--port", type=int, default=None)
    p_up.add_argument("--timeout", type=int, default=90)
    p_up.set_defaults(func=_cmd_up, async_=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "async_", False):
        return int(asyncio.run(args.func(args)))
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
