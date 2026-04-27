"""Canonical free-tier provider catalog.

Source of truth for "what free LLMs / multimodal endpoints we route through."
Curated manually; agent pipeline can SUGGEST updates via PR but never
auto-merges. Verify monthly — providers shift free tiers quarterly.

Per-model rate-limit semantics (matters for chain ordering):

- Groq, Cerebras, Gemini, OpenRouter (:free), NVIDIA NIM, Mistral —
  rate limits are PER MODEL. Multiple ProviderEntry rows for the
  same provider give effectively additive throughput, because
  `quotas.py` keys on `provider:model` (not `provider`).
  Example: groq/llama-3.3-70b-versatile burning out at 14,400 RPD
  does NOT block groq/llama-3.1-8b-instant (separate 14,400 RPD pool).

- HuggingFace Inference, Cohere, Voyage, Replicate, fal.ai,
  ElevenLabs, SambaNova — rate limits are PER ACCOUNT (shared pool
  or single credit balance). Multi-model rotation does NOT help.
  Catalog keeps one canonical entry per such provider per modality.

Effective throughput = sum of per-model pools where rotation helps,
PLUS per-account budgets where it doesn't.
"""

from __future__ import annotations

from datetime import date

from freellm.schemas import (
    AlwaysFreeWithLimits,
    Modality,
    OneTimeCredits,
    ProviderEntry,
    RequestsPerDay,
    RpmRpd,
)

LAST_CATALOG_REVIEW = date(2026, 4, 26)


# Convenience constructors keep the catalog rows compact.
def _rpm_rpd(rpm: int | None = None, rpd: int | None = None, **kw: object) -> RpmRpd:
    return RpmRpd(rpm=rpm, rpd=rpd, **kw)  # type: ignore[arg-type]


def _rpd(rpd: int, **kw: object) -> RequestsPerDay:
    return RequestsPerDay(rpd=rpd, **kw)  # type: ignore[arg-type]


def _credits(usd: float, **kw: object) -> OneTimeCredits:
    return OneTimeCredits(usd=usd, **kw)  # type: ignore[arg-type]


def _free_with_limits(notes: str) -> AlwaysFreeWithLimits:
    return AlwaysFreeWithLimits(notes=notes)


PROVIDERS: dict[Modality, list[ProviderEntry]] = {
    # ============================================================
    # text — chat / completion
    # ============================================================
    "text": [
        ProviderEntry(
            provider="groq",
            model="llama-3.3-70b-versatile",
            free_tier=_rpm_rpd(rpm=30, rpd=14400),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
            docs_url="https://console.groq.com/docs/rate-limits",
            notes="Fastest hosted Llama. Quotas reset daily.",
        ),
        ProviderEntry(
            provider="groq",
            model="llama-3.1-8b-instant",
            free_tier=_rpm_rpd(rpm=30, rpd=14400),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
            notes="Separate per-model RPD pool from llama-3.3-70b.",
        ),
        ProviderEntry(
            provider="groq",
            model="llama-3.2-3b-preview",
            free_tier=_rpm_rpd(rpm=30, rpd=14400),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
            notes="Tiny + fast; separate RPD pool.",
        ),
        ProviderEntry(
            provider="groq",
            model="mixtral-8x7b-32768",
            free_tier=_rpm_rpd(rpm=30, rpd=14400),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
            notes="Mixtral on Groq; 32k context; separate RPD pool.",
        ),
        ProviderEntry(
            provider="groq",
            model="gemma2-9b-it",
            free_tier=_rpm_rpd(rpm=30, rpd=14400),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
            notes="Gemma 2 9B; separate RPD pool.",
        ),
        ProviderEntry(
            provider="cerebras",
            model="llama3.1-70b",
            free_tier=_rpd(rpd=14400),
            env_var="CEREBRAS_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
            docs_url="https://cloud.cerebras.ai/",
            notes="Among fastest LLM inference; sometimes waitlisted.",
        ),
        ProviderEntry(
            provider="cerebras",
            model="llama3.1-8b",
            free_tier=_rpd(rpd=14400),
            env_var="CEREBRAS_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
            notes="Cerebras 8B; separate RPD pool.",
        ),
        ProviderEntry(
            provider="cerebras",
            model="llama-3.3-70b",
            free_tier=_rpd(rpd=14400),
            env_var="CEREBRAS_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
            notes="Cerebras Llama 3.3 70B; separate RPD pool.",
        ),
        ProviderEntry(
            provider="gemini",
            model="gemini-2.0-flash-exp",
            free_tier=_rpd(rpd=1500),
            env_var="GEMINI_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
            docs_url="https://ai.google.dev/pricing",
            notes="Generous free RPD. Vision-capable.",
        ),
        ProviderEntry(
            provider="gemini",
            model="gemini-1.5-flash",
            free_tier=_rpd(rpd=1500),
            env_var="GEMINI_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
            notes="Separate per-model RPD pool from gemini-2.0-flash-exp.",
        ),
        ProviderEntry(
            provider="gemini",
            model="gemini-1.5-flash-8b",
            free_tier=_rpd(rpd=1500),
            env_var="GEMINI_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
            notes="8B variant; separate RPD pool, smaller capacity.",
        ),
        ProviderEntry(
            provider="gemini",
            model="gemini-1.5-pro",
            free_tier=_rpd(rpd=50),
            env_var="GEMINI_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 22),
            notes="Pro tier; separate (small) RPD pool but better quality.",
        ),
        ProviderEntry(
            provider="openrouter",
            model="meta-llama/llama-3.1-70b-instruct:free",
            free_tier=_free_with_limits("Free :free model variants. Per-model RPM caps."),
            env_var="OPENROUTER_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 24),
            docs_url="https://openrouter.ai/models?supported_parameters=free",
        ),
        ProviderEntry(
            provider="openrouter",
            model="google/gemini-flash-1.5:free",
            free_tier=_free_with_limits("Free :free variant via OpenRouter."),
            env_var="OPENROUTER_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
        ),
        ProviderEntry(
            provider="openrouter",
            model="deepseek/deepseek-chat:free",
            free_tier=_free_with_limits("DeepSeek-V2.5 :free; per-model RPM cap."),
            env_var="OPENROUTER_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 24),
        ),
        ProviderEntry(
            provider="openrouter",
            model="qwen/qwen-2.5-72b-instruct:free",
            free_tier=_free_with_limits("Qwen 2.5 72B :free."),
            env_var="OPENROUTER_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 24),
        ),
        ProviderEntry(
            provider="together_ai",
            model="meta-llama/Llama-3.1-8B-Instruct-Turbo",
            free_tier=_credits(1.0, notes="$1 starter + select Free models."),
            env_var="TOGETHER_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 21),
            docs_url="https://www.together.ai/pricing",
        ),
        ProviderEntry(
            provider="together_ai",
            model="meta-llama/Llama-3.2-3B-Instruct-Turbo",
            free_tier=_credits(1.0, notes="Free serverless; smaller model."),
            env_var="TOGETHER_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 21),
        ),
        ProviderEntry(
            provider="mistral",
            model="open-mistral-7b",
            free_tier=_free_with_limits("Free tier rate-limited. Phone OTP signup."),
            env_var="MISTRAL_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 21),
            docs_url="https://docs.mistral.ai/",
        ),
        ProviderEntry(
            provider="mistral",
            model="open-mixtral-8x7b",
            free_tier=_free_with_limits("Mixtral 8x7B free tier."),
            env_var="MISTRAL_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 21),
        ),
        ProviderEntry(
            provider="mistral",
            model="codestral-latest",
            free_tier=_free_with_limits("Codestral free tier; code-specialised."),
            env_var="MISTRAL_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 21),
        ),
        ProviderEntry(
            provider="nvidia_nim",
            model="meta/llama-3.1-70b-instruct",
            free_tier=_rpd(rpd=1000),
            env_var="NVIDIA_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 19),
            docs_url="https://build.nvidia.com/",
            notes="NVIDIA NIM credits per model; separate RPD pools.",
        ),
        ProviderEntry(
            provider="nvidia_nim",
            model="meta/llama-3.1-8b-instruct",
            free_tier=_rpd(rpd=1000),
            env_var="NVIDIA_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 19),
        ),
        ProviderEntry(
            provider="nvidia_nim",
            model="mistralai/mixtral-8x7b-instruct-v0.1",
            free_tier=_rpd(rpd=1000),
            env_var="NVIDIA_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 19),
        ),
        ProviderEntry(
            provider="sambanova",
            model="Meta-Llama-3.3-70B-Instruct",
            free_tier=_rpd(rpd=1000),
            env_var="SAMBANOVA_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 21),
            docs_url="https://cloud.sambanova.ai/",
        ),
        ProviderEntry(
            provider="huggingface",
            model="meta-llama/Meta-Llama-3-8B-Instruct",
            free_tier=_free_with_limits(
                "HF Inference API; SHARED pool across models. Multi-model "
                "rotation does NOT add throughput here."
            ),
            env_var="HF_TOKEN",
            speed_tier="slow",
            last_verified=date(2026, 4, 19),
            docs_url="https://huggingface.co/docs/api-inference/index",
        ),
    ],
    # ============================================================
    # vision — text + image input -> text output
    # ============================================================
    "vision": [
        ProviderEntry(
            provider="gemini",
            model="gemini-1.5-flash",
            free_tier=_rpd(rpd=1500),
            env_var="GEMINI_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
        ),
        ProviderEntry(
            provider="groq",
            model="llama-3.2-90b-vision-preview",
            free_tier=_rpm_rpd(rpm=15, rpd=3500),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
        ),
        ProviderEntry(
            provider="groq",
            model="llama-3.2-11b-vision-preview",
            free_tier=_rpm_rpd(rpm=15, rpd=3500),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
            notes="Smaller vision model; separate RPD pool from 90B.",
        ),
        ProviderEntry(
            provider="openrouter",
            model="meta-llama/llama-3.2-11b-vision-instruct:free",
            free_tier=_free_with_limits("Free :free vision via OpenRouter."),
            env_var="OPENROUTER_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 24),
        ),
        ProviderEntry(
            provider="openrouter",
            model="qwen/qwen-2-vl-72b-instruct:free",
            free_tier=_free_with_limits("Qwen 2 VL :free."),
            env_var="OPENROUTER_API_KEY",
            speed_tier="medium",
            last_verified=date(2026, 4, 24),
        ),
    ],
    # ============================================================
    # image_gen
    # ============================================================
    "image_gen": [
        ProviderEntry(
            provider="huggingface",
            model="black-forest-labs/FLUX.1-schnell",
            free_tier=_free_with_limits("HF Inference free; shared pool."),
            env_var="HF_TOKEN",
            speed_tier="slow",
            last_verified=date(2026, 4, 19),
        ),
        ProviderEntry(
            provider="together_ai",
            model="black-forest-labs/FLUX.1-schnell-Free",
            free_tier=_free_with_limits("Free FLUX-schnell on Together."),
            env_var="TOGETHER_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 21),
        ),
        ProviderEntry(
            provider="replicate",
            model="black-forest-labs/flux-schnell",
            free_tier=_credits(1.0, notes="Small monthly free compute."),
            env_var="REPLICATE_API_TOKEN",
            speed_tier="medium",
            last_verified=date(2026, 4, 19),
        ),
        ProviderEntry(
            provider="fal_ai",
            model="fal-ai/flux/schnell",
            free_tier=_credits(1.0, notes="Signup credits + free quota on fast models."),
            env_var="FAL_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 19),
        ),
    ],
    # ============================================================
    # video_gen
    # ============================================================
    "video_gen": [
        ProviderEntry(
            provider="replicate",
            model="stability-ai/stable-video-diffusion",
            free_tier=_credits(1.0, notes="Limited free quota."),
            env_var="REPLICATE_API_TOKEN",
            speed_tier="slow",
            last_verified=date(2026, 4, 19),
        ),
        ProviderEntry(
            provider="fal_ai",
            model="fal-ai/animatediff-v2v",
            free_tier=_credits(1.0, notes="Limited free quota."),
            env_var="FAL_API_KEY",
            speed_tier="slow",
            last_verified=date(2026, 4, 19),
        ),
    ],
    # ============================================================
    # embed
    # ============================================================
    "embed": [
        ProviderEntry(
            provider="voyage",
            model="voyage-3-lite",
            free_tier=AlwaysFreeWithLimits(notes="50M tokens lifetime free."),
            env_var="VOYAGE_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 18),
            docs_url="https://docs.voyageai.com/docs/pricing",
        ),
        ProviderEntry(
            provider="cohere",
            model="embed-english-v3.0",
            free_tier=_free_with_limits("Trial key; rate-limited."),
            env_var="COHERE_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 18),
        ),
        ProviderEntry(
            provider="mistral",
            model="mistral-embed",
            free_tier=_free_with_limits("Free tier rate-limited."),
            env_var="MISTRAL_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 21),
        ),
        ProviderEntry(
            provider="gemini",
            model="text-embedding-004",
            free_tier=_rpd(rpd=1500),
            env_var="GEMINI_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 22),
        ),
        ProviderEntry(
            provider="huggingface",
            model="sentence-transformers/all-MiniLM-L6-v2",
            free_tier=_free_with_limits("HF Inference free."),
            env_var="HF_TOKEN",
            speed_tier="slow",
            last_verified=date(2026, 4, 19),
        ),
    ],
    # ============================================================
    # stt — speech to text
    # ============================================================
    "stt": [
        ProviderEntry(
            provider="groq",
            model="whisper-large-v3",
            free_tier=_rpm_rpd(rpm=20, rpd=2000),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
        ),
        ProviderEntry(
            provider="groq",
            model="whisper-large-v3-turbo",
            free_tier=_rpm_rpd(rpm=20, rpd=2000),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
            notes="Turbo Whisper; separate RPD pool from large-v3.",
        ),
        ProviderEntry(
            provider="groq",
            model="distil-whisper-large-v3-en",
            free_tier=_rpm_rpd(rpm=20, rpd=2000),
            env_var="GROQ_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 24),
            notes="Distil-Whisper EN-only; separate RPD pool.",
        ),
        ProviderEntry(
            provider="huggingface",
            model="openai/whisper-large-v3",
            free_tier=_free_with_limits("HF Inference free; shared pool."),
            env_var="HF_TOKEN",
            speed_tier="slow",
            last_verified=date(2026, 4, 19),
        ),
    ],
    # ============================================================
    # tts
    # ============================================================
    "tts": [
        ProviderEntry(
            provider="huggingface",
            model="suno/bark",
            free_tier=_free_with_limits("HF Inference free."),
            env_var="HF_TOKEN",
            speed_tier="slow",
            last_verified=date(2026, 4, 19),
        ),
        ProviderEntry(
            provider="elevenlabs",
            model="eleven_turbo_v2_5",
            free_tier=AlwaysFreeWithLimits(notes="10,000 chars/month free."),
            env_var="ELEVENLABS_API_KEY",
            speed_tier="fast",
            last_verified=date(2026, 4, 19),
            docs_url="https://elevenlabs.io/pricing",
        ),
    ],
}


def list_providers(modality: Modality | None = None) -> list[ProviderEntry]:
    """Return catalog rows from the LIVE layered config (built-in + YAML +
    programmatic configure()). Use `freellm.PROVIDERS` directly only when
    you specifically want the unmodified built-in defaults.
    """
    # Late import keeps this function safe to call from inside config.py.
    from freellm.config import get_config

    cfg = get_config()
    if modality is not None:
        return list(cfg.providers.get(modality, []))
    out: list[ProviderEntry] = []
    for entries in cfg.providers.values():
        out.extend(entries)
    return out
