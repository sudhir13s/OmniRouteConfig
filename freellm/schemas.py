"""Pydantic models for freellm — request / response / catalog shapes."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# `model` is a legitimate domain term (LLM model id) — opt out of Pydantic's
# protected `model_` namespace globally for this module.
_NO_PROTECTED_NS = ConfigDict(protected_namespaces=())

# === Modalities ===

Modality = Literal[
    "text",
    "vision",
    "image_gen",
    "video_gen",
    "embed",
    "stt",
    "tts",
]

ALL_MODALITIES: tuple[Modality, ...] = (
    "text",
    "vision",
    "image_gen",
    "video_gen",
    "embed",
    "stt",
    "tts",
)

SpeedTier = Literal["fast", "medium", "slow"]


# === Free-tier quota descriptors ===
# Each provider entry carries one of these in its `free_tier` field. Discriminated
# by `kind` so the router can branch quota logic without isinstance checks.


class RpmRpd(BaseModel):
    """Requests-per-minute + requests-per-day caps. Most common shape."""

    kind: Literal["rpm_rpd"] = "rpm_rpd"
    rpm: int | None = None
    rpd: int | None = None
    tokens_per_minute: int | None = None
    notes: str | None = None


class TokensPerMonth(BaseModel):
    kind: Literal["tokens_per_month"] = "tokens_per_month"
    tokens_per_month: int
    notes: str | None = None


class RequestsPerDay(BaseModel):
    kind: Literal["requests_per_day"] = "requests_per_day"
    rpd: int
    notes: str | None = None


class OneTimeCredits(BaseModel):
    kind: Literal["one_time_credits"] = "one_time_credits"
    usd: float
    notes: str | None = None


class AlwaysFreeWithLimits(BaseModel):
    kind: Literal["always_free_with_limits"] = "always_free_with_limits"
    notes: str  # e.g. "free with rate caps; HF Inference shared pool"


FreeTier = Annotated[
    RpmRpd | TokensPerMonth | RequestsPerDay | OneTimeCredits | AlwaysFreeWithLimits,
    Field(discriminator="kind"),
]


# === Provider catalog entry ===


class ProviderEntry(BaseModel):
    """One row in `providers.PROVIDERS[modality]`."""

    model_config = _NO_PROTECTED_NS

    provider: str  # litellm slug, e.g. "groq", "gemini", "openrouter"
    model: str  # litellm model id, e.g. "llama-3.3-70b-versatile"
    free_tier: FreeTier
    env_var: str  # API key env var, e.g. "GROQ_API_KEY"
    speed_tier: SpeedTier = "medium"
    last_verified: date
    geo_restrictions: list[str] = Field(default_factory=list)  # ISO codes
    notes: str | None = None
    docs_url: str | None = None


# === Runtime types ===


class Result(BaseModel):
    """Returned by every successful call_* invocation."""

    model_config = _NO_PROTECTED_NS

    content: str  # for text / vision / stt; URL for image_gen / video_gen / tts
    provider_used: str
    model_used: str
    latency_ms: int
    cost_usd: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None
    chain_attempted: list[str] = Field(default_factory=list)


class PlanOption(BaseModel):
    model_config = _NO_PROTECTED_NS

    provider: str
    model: str
    env_var_present: bool
    quota_remaining: str  # human-readable; full state in `quotas.py`
    speed_tier: SpeedTier
    free_tier_kind: str  # discriminator value


class Plan(BaseModel):
    """Returned by `plan()` and the `dry_run=True` flag on call_*."""

    modality: Modality
    task_name: str
    options: list[PlanOption]
    chosen: PlanOption | None  # None if every entry filtered out
    reason_skipped: dict[str, str] = Field(default_factory=dict)
