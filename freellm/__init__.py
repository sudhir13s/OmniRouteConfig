"""freellm — free-LLM router library.

Curated catalog of free-tier LLM / multimodal providers, with quota-aware
fallback routing so total spend stays at $0. Reusable as a library
across projects.

Public API:

    from freellm import (
        call_text, call_vision, call_image_gen, call_video_gen,
        call_embed, call_stt, call_tts,
        Result, Plan, ProviderEntry,
        AllProvidersExhaustedError,
        # Config layer
        configure, get_config, reset, load_from_yaml,
    )

v0.1 ships the contract + dry-run `plan()` + persistent quota tracker
+ catalog (28+ entries across 7 modalities) + config layer (YAML +
programmatic). Live LiteLLM dispatch lands in v0.2.
"""

from __future__ import annotations

from freellm.config import (
    FreellmConfig,
    configure,
    get_config,
    load_from_yaml,
    reset,
)
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

__version__ = "0.2.0"

__all__ = [
    "PROVIDERS",
    "AllProvidersExhaustedError",
    "FreellmConfig",
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
    "configure",
    "get_config",
    "list_providers",
    "load_from_yaml",
    "plan",
    "reset",
]
