"""Catalog loader — parses config/free-providers.yaml into typed rows."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "config" / "free-providers.yaml"

_NO_PROTECTED_NS = ConfigDict(protected_namespaces=())


class ProviderEntry(BaseModel):
    """One row in the catalog. Maps an OmniRoute provider to the env var
    holding its API key + optional metadata to push on POST.
    """

    model_config = _NO_PROTECTED_NS

    provider: str = Field(
        description=(
            "OmniRoute provider id. Must match an id known to OmniRoute "
            "(see OmniRoute's src/shared/constants/providers.ts)."
        ),
    )
    env_var: str = Field(
        description="Name of the env var holding the API key (e.g. GROQ_API_KEY)."
    )
    aliases: list[str] | None = Field(
        default=None,
        description=(
            "Alternate env var names that env_sync should accept as fallback "
            "when the canonical `env_var` is empty. Useful when shells have a "
            "differently-named key (e.g. CLAUDE_CONSOLE_API_KEY for ANTHROPIC_API_KEY). "
            "First non-empty wins."
        ),
    )
    name: str | None = Field(
        default=None,
        description="Human label sent to OmniRoute on POST. Defaults to provider id.",
    )
    priority: int = Field(
        default=100,
        description="Lower = higher priority in OmniRoute's chain.",
    )
    default_model: str | None = Field(
        default=None,
        description="Optional preferred model id.",
    )
    enabled: bool = Field(
        default=True,
        description="Set False to keep the row but not POST it.",
    )
    note: str | None = None
    provider_specific_data: dict[str, Any] | None = Field(
        default=None,
        description="Free-form passthrough to OmniRoute's providerSpecificData.",
    )


class ProviderCatalog(BaseModel):
    """Top-level catalog file shape."""

    version: int = 1
    providers: list[ProviderEntry] = Field(default_factory=list)


def _resolve_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    env = os.environ.get("OMNI_ROUTE_CONFIG_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_CATALOG_PATH


def load_catalog(path: str | Path | None = None) -> ProviderCatalog:
    """Read + validate the YAML catalog.

    Precedence (last wins):
      1. explicit `path` argument
      2. `OMNI_ROUTE_CONFIG_PATH` env var
      3. bundled default at `<repo>/config/free-providers.yaml`

    Raises FileNotFoundError if no readable file is found.
    """
    p = _resolve_path(path)
    if not p.exists():
        raise FileNotFoundError(f"Catalog not found at {p}")
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{p}: top-level must be a mapping")
    return ProviderCatalog.model_validate(raw)


def env_var_present(entry: ProviderEntry) -> bool:
    """True if the env var named in `entry.env_var` is set + non-empty."""
    return bool(os.environ.get(entry.env_var, "").strip())


def filter_runnable(catalog: ProviderCatalog) -> list[ProviderEntry]:
    """Subset of catalog entries where enabled + the env var is set.

    These are the rows we'll actually POST to OmniRoute.
    """
    return [e for e in catalog.providers if e.enabled and env_var_present(e)]
