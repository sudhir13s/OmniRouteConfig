"""Quota-aware fallback chain executor.

v0.1 status: ships the contract + a working `plan()` (dry-run) so the
dashboard's "Test the chain" UX has data to render. The actual
`call_text()` etc. live calls land in v0.2 once LiteLLM is added as a
dependency.

Per `agentic-pipeline.md` rule, this file is the ONLY place allowed to
import `litellm`. v0.1 doesn't import it yet; v0.2 will.
"""

from __future__ import annotations

import os
from typing import Any

from freellm import quotas
from freellm.config import get_config
from freellm.providers import list_providers
from freellm.schemas import (
    Modality,
    Plan,
    PlanOption,
    ProviderEntry,
    Result,
)


class AllProvidersExhaustedError(RuntimeError):
    """Raised when every provider in the chain has been tried + failed."""

    def __init__(self, chain_attempted: list[str]):
        self.chain_attempted = chain_attempted
        super().__init__(
            f"All free providers exhausted. Attempted: {', '.join(chain_attempted)}"
        )


def _filter_chain(
    entries: list[ProviderEntry], state: quotas.QuotaState, allow_paid: bool
) -> tuple[list[tuple[ProviderEntry, PlanOption]], dict[str, str]]:
    """Apply env-var + disable + quota filters. Returns (kept, reason_skipped)."""
    kept: list[tuple[ProviderEntry, PlanOption]] = []
    skipped: dict[str, str] = {}
    for e in entries:
        key = f"{e.provider}/{e.model}"
        if not allow_paid and not os.environ.get(e.env_var):
            skipped[key] = f"missing env var {e.env_var}"
            continue
        usage = quotas.get(state, e.provider, e.model)
        if quotas.is_disabled(usage):
            skipped[key] = f"disabled until {usage.disabled_until}"
            continue
        opt = PlanOption(
            provider=e.provider,
            model=e.model,
            env_var_present=bool(os.environ.get(e.env_var)),
            quota_remaining=quotas.remaining_hint(usage),
            speed_tier=e.speed_tier,
            free_tier_kind=e.free_tier.kind,  # type: ignore[union-attr]
        )
        kept.append((e, opt))
    return kept, skipped


def plan(
    *,
    modality: Modality,
    task_name: str,
    allow_paid: bool | None = None,
) -> Plan:
    """Compute the route a call would take WITHOUT making the call.

    Used by the dashboard's "Test the chain" button + the `python -m freellm
    plan` CLI subcommand. No network, no LiteLLM import, safe to call
    cheaply.
    """
    if allow_paid is None:
        allow_paid = os.environ.get("LLM_ALLOW_PAID") == "1"
    entries = get_config().providers.get(modality, [])
    state = quotas.load()
    kept, skipped = _filter_chain(entries, state, allow_paid=allow_paid)
    options = [opt for _, opt in kept]
    chosen = options[0] if options else None
    return Plan(
        modality=modality,
        task_name=task_name,
        options=options,
        chosen=chosen,
        reason_skipped=skipped,
    )


# ============================================================
# Modality-specific call_* entry points.
# ============================================================
# v0.1 contract: each function accepts the locked kwargs, returns a Result
# OR raises AllProvidersExhaustedError. Live execution arrives in v0.2 when
# LiteLLM is wired in.
#
# When dry_run=True, every call_* returns a Plan rather than a Result so
# callers can preview routing without hitting the network.
# ============================================================


def _not_implemented(modality: Modality) -> Result:
    raise NotImplementedError(
        f"freellm.call_{modality}() runtime is v0.2 work. "
        "v0.1 ships only the contract + dry_run=True plan(). "
        "Use `from freellm import plan; plan(modality='...', task_name='...')` "
        "to preview routing."
    )


async def call_text(
    *,
    messages: list[dict[str, Any]],
    task_name: str,
    model_chain: list[str] | None = None,
    response_model: type | None = None,
    max_tokens: int = 2000,
    temperature: float = 0.0,
    timeout_s: int = 60,
    dry_run: bool = False,
) -> Result | Plan:
    if dry_run:
        return plan(modality="text", task_name=task_name)
    _ = (messages, model_chain, response_model, max_tokens, temperature, timeout_s)
    return _not_implemented("text")


async def call_vision(
    *,
    messages: list[dict[str, Any]],
    image_bytes: bytes | None = None,
    task_name: str,
    dry_run: bool = False,
) -> Result | Plan:
    if dry_run:
        return plan(modality="vision", task_name=task_name)
    _ = (messages, image_bytes)
    return _not_implemented("vision")


async def call_image_gen(
    *,
    prompt: str,
    task_name: str,
    width: int = 1024,
    height: int = 1024,
    dry_run: bool = False,
) -> Result | Plan:
    if dry_run:
        return plan(modality="image_gen", task_name=task_name)
    _ = (prompt, width, height)
    return _not_implemented("image_gen")


async def call_video_gen(
    *,
    prompt: str,
    task_name: str,
    duration_s: float = 4.0,
    resolution: str = "720p",
    dry_run: bool = False,
) -> Result | Plan:
    if dry_run:
        return plan(modality="video_gen", task_name=task_name)
    _ = (prompt, duration_s, resolution)
    return _not_implemented("video_gen")


async def call_embed(
    *,
    inputs: list[str],
    task_name: str,
    dry_run: bool = False,
) -> Result | Plan:
    if dry_run:
        return plan(modality="embed", task_name=task_name)
    _ = inputs
    return _not_implemented("embed")


async def call_stt(
    *,
    audio_bytes: bytes,
    task_name: str,
    language: str | None = None,
    dry_run: bool = False,
) -> Result | Plan:
    if dry_run:
        return plan(modality="stt", task_name=task_name)
    _ = (audio_bytes, language)
    return _not_implemented("stt")


async def call_tts(
    *,
    text: str,
    task_name: str,
    voice: str | None = None,
    dry_run: bool = False,
) -> Result | Plan:
    if dry_run:
        return plan(modality="tts", task_name=task_name)
    _ = (text, voice)
    return _not_implemented("tts")


# Pure-function helper for catalog inspection (used by CLI + tests).
def catalog_summary() -> dict[str, int]:
    """Return modality -> count of entries (in the live, layered config)."""
    return {
        modality: len(entries)
        for modality, entries in get_config().providers.items()
    }


def total_entries() -> int:
    return sum(len(e) for e in get_config().providers.values())


def list_all() -> list[ProviderEntry]:
    """Return every catalog row across all modalities."""
    return list_providers()
