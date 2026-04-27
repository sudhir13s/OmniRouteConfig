"""freellm — free-LLM router library.

Curated catalog of free-tier LLM / multimodal providers, with quota-aware
fallback routing so total spend stays at $0. Reusable as a library outside
this project; designed to graduate to its own PyPI package later.

Public API (v0.2 will fully implement; v0.1 ships the contract + dry-run
plan only):

    from freellm import (
        call_text, call_vision, call_image_gen, call_video_gen,
        call_embed, call_stt, call_tts,
        Result, Plan, ProviderEntry,
        AllProvidersExhaustedError,
    )

See `.claude/rules/project/freellm-router.md` for the full spec.
"""

from __future__ import annotations

from freellm.providers import PROVIDERS, list_providers
from freellm.router import (
    AllProvidersExhaustedError,
    call_embed,
    call_image_gen,
    call_stt,
    call_text,
    call_tts,
    call_video_gen,
    call_vision,
    plan,
)
from freellm.schemas import Modality, Plan, ProviderEntry, Result

__version__ = "0.1.0"

__all__ = [
    "PROVIDERS",
    "AllProvidersExhaustedError",
    "Modality",
    "Plan",
    "ProviderEntry",
    "Result",
    "__version__",
    "call_embed",
    "call_image_gen",
    "call_stt",
    "call_text",
    "call_tts",
    "call_video_gen",
    "call_vision",
    "list_providers",
    "plan",
]
