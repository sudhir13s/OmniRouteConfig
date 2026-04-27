"""Pydantic models exposed in the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ModelType = Literal["chat", "embedding", "image", "audio", "rerank", "moderation", "video", "music"]

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


class ModelEntry(BaseModel):
    """One model exposed by an OmniRoute provider, derived from /api/v1/models."""

    model_config = _NO_PROTECTED_NS

    id: str = Field(description="Model id (e.g. 'llama-3.3-70b-versatile').")
    provider: str = Field(description="OmniRoute provider id (owned_by).")
    type: ModelType = Field(default="chat", description="Modality category.")
    subtype: str | None = Field(
        default=None,
        description="Refinement within type (e.g. 'transcription' / 'speech' for audio).",
    )
    context_length: int | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    custom: bool = Field(
        default=False,
        description="True if registered as a custom model (non-canonical).",
    )
    api_format: str | None = Field(
        default=None,
        description="Wire format (e.g. 'chat-completions') when provider is OpenAI-compatible.",
    )


class ProviderRegistry(BaseModel):
    """Live snapshot of providers + models pulled from a running OmniRoute."""

    model_config = _NO_PROTECTED_NS

    base_url: str
    fetched_at: datetime
    providers: dict[str, list[ModelEntry]] = Field(
        default_factory=dict,
        description="Provider id → list of models that provider exposes.",
    )
    connections: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw /api/providers connections (id, label, isActive, priority).",
    )

    def model_count(self) -> int:
        return sum(len(ms) for ms in self.providers.values())

    def by_type(self, model_type: ModelType) -> list[ModelEntry]:
        out: list[ModelEntry] = []
        for ms in self.providers.values():
            out.extend(m for m in ms if m.type == model_type)
        return out


class SyncDiff(BaseModel):
    """Result of comparing local YAML catalog vs live OmniRoute registry."""

    in_yaml_only: list[str] = Field(
        default_factory=list,
        description="Provider ids in YAML but not surfaced by OmniRoute (stale).",
    )
    in_remote_only: list[str] = Field(
        default_factory=list,
        description="Provider ids OmniRoute exposes but YAML doesn't list (additions).",
    )
    matched: list[str] = Field(
        default_factory=list,
        description="Provider ids present on both sides (healthy).",
    )
