"""Env synchronization — read shell env, persist to .env, generate OmniRoute secrets.

The CLI flow `omniroutectl up` needs a single `.env` that contains:

  1. Provider API keys (catalog `env_var` names) read from the user's shell.
  2. OmniRoute server-side secrets (JWT_SECRET, API_KEY_SECRET, STORAGE_ENCRYPTION_KEY,
     INITIAL_PASSWORD) — generated once, persisted, never overwritten.
  3. OmniRoute runtime config (PORT, INSTANCE_NAME, BASE_URL, etc.) with stable defaults.

Precedence on every value (highest wins):

    existing .env file  >  shell env  >  generated default

Existing values are NEVER overwritten so secrets stay stable across `omniroutectl up` runs
(if we rolled the JWT secret on every restart, every admin session would die).
"""

from __future__ import annotations

import os
import secrets
import string
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from omni_route_config.catalog import ProviderCatalog, load_catalog

# ============================================================
# Static contract
# ============================================================

# OmniRoute server-side env vars we own. Anything else (timeouts, OAuth client
# IDs, user agents, CLI binaries, ...) the user can add to .env manually —
# we read .env into Docker, so additional rows pass through.
# Auto-generated only on first run when missing from .env AND shell.
# `INITIAL_PASSWORD` is INTENTIONALLY excluded — it controls the dashboard
# admin password. Letting an automated tool randomise it surprises users
# (they sign up via the dashboard form themselves). Set it manually in
# .env or in your shell if you want a non-default seed.
SERVER_SECRETS = (
    "JWT_SECRET",  # base64 48 — admin session signing
    "API_KEY_SECRET",  # hex 32   — bearer-token HMAC
    "STORAGE_ENCRYPTION_KEY",  # hex 32  — at-rest encryption for SQLite-stored secrets
    "MACHINE_ID_SALT",  # 16 chars — fingerprint stability salt
)

# User-managed secrets we surface (write a blank slot for visibility) but
# NEVER auto-generate. Existing values are preserved.
USER_MANAGED_SECRETS = ("INITIAL_PASSWORD",)

SERVER_DEFAULTS = {
    "NODE_ENV": "production",
    "PORT": "20128",
    "INSTANCE_NAME": "omniroute",
    "DATA_DIR": "/app/data",
    "STORAGE_DRIVER": "sqlite",
    "STORAGE_ENCRYPTION_KEY_VERSION": "v1",
    "BASE_URL": "http://localhost:20128",
    "NEXT_PUBLIC_BASE_URL": "http://localhost:20128",
    "AUTH_COOKIE_SECURE": "false",
    "REQUIRE_API_KEY": "false",
    "ALLOW_API_KEY_REVEAL": "false",
    "PROVIDER_LIMITS_SYNC_INTERVAL_MINUTES": "70",
    "DISABLE_SQLITE_AUTO_BACKUP": "false",
}

PASSWORD_ALPHABET = string.ascii_letters + string.digits


@dataclass
class SyncReport:
    """What `sync_env_file` did. Returned to the CLI for human-readable output."""

    path: Path
    provider_keys_from_shell: list[str]
    provider_keys_missing: list[str]
    secrets_generated: list[str]
    secrets_preserved: list[str]
    server_defaults_added: list[str]


# ============================================================
# Secret generators
# ============================================================


def _gen_base64(num_bytes: int) -> str:
    """URL-safe base64 (matches `openssl rand -base64 N` shape closely enough
    for OmniRoute's JWT_SECRET — the server treats the value as opaque)."""
    return secrets.token_urlsafe(num_bytes)


def _gen_hex(num_bytes: int) -> str:
    """Hex string of `num_bytes` bytes (so length = 2*num_bytes)."""
    return secrets.token_hex(num_bytes)


def _gen_password(length: int = 24) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def _generate_secret(name: str) -> str:
    if name == "JWT_SECRET":
        return _gen_base64(48)
    if name == "API_KEY_SECRET" or name == "STORAGE_ENCRYPTION_KEY":
        return _gen_hex(32)
    if name == "MACHINE_ID_SALT":
        return _gen_password(16)
    raise ValueError(f"No generator for secret {name!r}")


# ============================================================
# Dotenv parser / writer
# ============================================================


def parse_dotenv(path: Path) -> dict[str, str]:
    """Tolerant parser. Skips comments/blank lines. Strips matching quotes.

    Does NOT do shell expansion — values containing `$VAR` are preserved as-is.
    """
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        out[k] = v
    return out


def write_dotenv(
    path: Path,
    values: dict[str, str],
    *,
    section_order: Iterable[tuple[str, list[str]]] | None = None,
) -> None:
    """Write `values` to `path`. Preserves a stable section ordering when provided.

    Keys not listed in any section are written under a trailing `# Other` block.
    """
    section_order = list(section_order or [])
    seen: set[str] = set()
    lines: list[str] = []

    for title, keys in section_order:
        section_lines: list[str] = []
        for k in keys:
            if k in values:
                section_lines.append(f"{k}={values[k]}")
                seen.add(k)
        if section_lines:
            lines.append(f"# {title}")
            lines.extend(section_lines)
            lines.append("")

    leftover = sorted(k for k in values if k not in seen)
    if leftover:
        lines.append("# Other")
        for k in leftover:
            lines.append(f"{k}={values[k]}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    # Best-effort permission tighten — secrets in here.
    try:
        path.chmod(0o600)
    except OSError:
        pass


# ============================================================
# Sync orchestration
# ============================================================


def _collect_provider_keys(catalog: ProviderCatalog) -> list[str]:
    """Catalog `env_var` names (deduped, in catalog order)."""
    seen: set[str] = set()
    out: list[str] = []
    for entry in catalog.providers:
        if entry.env_var not in seen:
            seen.add(entry.env_var)
            out.append(entry.env_var)
    return out


def sync_env_file(
    path: str | Path = ".env",
    *,
    catalog: ProviderCatalog | None = None,
    shell_env: dict[str, str] | None = None,
) -> SyncReport:
    """Merge existing-.env + shell-env + generated secrets → write `.env`.

    `shell_env=None` reads `os.environ`. Pass an explicit dict in tests.
    `catalog=None` reads the bundled catalog.
    """
    path = Path(path).expanduser()
    catalog = catalog or load_catalog()
    shell_env = shell_env if shell_env is not None else dict(os.environ)

    existing = parse_dotenv(path)
    merged: dict[str, str] = dict(existing)

    # 1. Provider keys: shell-env fills slots not already set in .env.
    #    For each entry, try the canonical env_var name first, then any
    #    declared aliases. First non-empty wins.
    provider_keys = _collect_provider_keys(catalog)
    aliases_for: dict[str, list[str]] = {
        e.env_var: list(e.aliases or []) for e in catalog.providers
    }
    keys_from_shell: list[str] = []
    keys_missing: list[str] = []
    for k in provider_keys:
        if merged.get(k):
            continue  # respect user's existing .env value
        candidates = [k, *aliases_for.get(k, [])]
        chosen_value = ""
        for cand in candidates:
            v = shell_env.get(cand, "").strip()
            if v:
                chosen_value = v
                break
        if chosen_value:
            merged[k] = chosen_value
            keys_from_shell.append(k)
        else:
            keys_missing.append(k)
            merged.setdefault(k, "")  # write blank slot so user sees it

    # 1b. User-managed secrets (e.g. INITIAL_PASSWORD): never auto-generate.
    #     Surface as blank slot if missing so the user sees it exists.
    for s in USER_MANAGED_SECRETS:
        if merged.get(s):
            continue
        seeded = shell_env.get(s, "").strip()
        merged[s] = seeded  # blank string OK

    # 2. Server-side secrets: generate only what's missing or empty.
    secrets_generated: list[str] = []
    secrets_preserved: list[str] = []
    for s in SERVER_SECRETS:
        if merged.get(s):
            secrets_preserved.append(s)
            continue
        # Allow shell to seed the secret too — useful in CI where you want
        # deterministic values.
        seeded = shell_env.get(s, "").strip()
        if seeded:
            merged[s] = seeded
            secrets_preserved.append(s)
        else:
            merged[s] = _generate_secret(s)
            secrets_generated.append(s)

    # 3. Server-side defaults: only add if not present.
    defaults_added: list[str] = []
    for k, v in SERVER_DEFAULTS.items():
        if merged.get(k):
            continue
        merged[k] = v
        defaults_added.append(k)

    sections = (
        (
            "OmniRouteConfig wiring",
            [
                "OMNIROUTE_URL",
                "OMNIROUTE_PORT",
                "OMNIROUTE_API_TOKEN",
                "OMNI_ROUTE_CONFIG_PATH",
            ],
        ),
        ("OmniRoute server secrets — DO NOT COMMIT", list(SERVER_SECRETS)),
        ("OmniRoute admin (you set this on dashboard signup)", list(USER_MANAGED_SECRETS)),
        ("OmniRoute server runtime", list(SERVER_DEFAULTS.keys())),
        ("Provider API keys", provider_keys),
    )
    write_dotenv(path, merged, section_order=sections)

    return SyncReport(
        path=path,
        provider_keys_from_shell=keys_from_shell,
        provider_keys_missing=keys_missing,
        secrets_generated=secrets_generated,
        secrets_preserved=secrets_preserved,
        server_defaults_added=defaults_added,
    )
