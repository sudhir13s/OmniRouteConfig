"""CLI entry: `python -m omni_route_config <subcommand>` or `omni-route-config <subcommand>`.

Subcommands:
  init         Ensure OmniRoute is running (starts via npx/docker if needed).
  configure    Read free-providers.yaml + env vars, POST to OmniRoute /api/providers.
  status       Print whether OmniRoute is reachable + how many providers it has.
  smoke-test   Send a dummy chat completion through the chain (requires `[client]` extra).
  catalog      Print the parsed catalog (validates the YAML).
  down         Stop the OmniRoute process WE started (no-op if external).
  version      Print this package version.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from omni_route_config import __version__
from omni_route_config.bootstrap import (
    apply_config,
    ensure_running,
    status,
    tear_down,
)
from omni_route_config.catalog import load_catalog


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
    _print({"killed": killed})
    return 0


# ---------- parser ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omni-route-config",
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
        "--prompt", default="Say 'omni-route-config online' and nothing else."
    )
    p_smoke.set_defaults(func=_cmd_smoke, async_=True)

    sub.add_parser("down", help="Stop the OmniRoute process this CLI started").set_defaults(
        func=cmd_down, async_=False
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "async_", False):
        return int(asyncio.run(args.func(args)))
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
