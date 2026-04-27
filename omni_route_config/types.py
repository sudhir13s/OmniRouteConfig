"""Pydantic models exposed in the public API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# `model` is a domain term (LLM model id) — opt out of Pydantic's
# protected `model_` namespace.
_NO_PROTECTED_NS = ConfigDict(protected_namespaces=())


class OmniRouteStatus(BaseModel):
    """Snapshot of the running OmniRoute server."""

    model_config = _NO_PROTECTED_NS

    base_url: str
    reachable: bool
    version: str | None = None
    instance_name: str | None = None
    providers_configured: int = 0
    detail: str | None = None


class ProviderApply(BaseModel):
    """Per-provider outcome from apply_config()."""

    model_config = _NO_PROTECTED_NS

    provider: str
    env_var: str
    status: Literal["applied", "skipped_missing_key", "already_present", "error"]
    detail: str | None = None
    omniroute_id: str | None = None


class ApplyResult(BaseModel):
    """Aggregate outcome of apply_config()."""

    total: int = Field(description="Catalog entries considered")
    applied: int = Field(description="Newly POSTed to OmniRoute")
    already_present: int = 0
    skipped_missing_key: int = 0
    errors: int = 0
    items: list[ProviderApply] = Field(default_factory=list)
