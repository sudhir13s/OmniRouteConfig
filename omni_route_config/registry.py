"""Live registry — pulls providers + models from a running OmniRoute.

OmniRoute owns the canonical list of supported providers and their models.
This module fetches both via REST, joins them on `owned_by`, and returns
a typed `ProviderRegistry`. Result is cached on disk under
`.omniroute/registry.json` with a 24h TTL so repeated `omniroutectl
models` calls don't hammer the server.

OmniRoute endpoints (verified against v3.7.x):
  GET /api/v1/models       OpenAI-compatible list with rich type metadata
                           (chat / embedding / image / audio / rerank /
                           moderation / video / music; `subtype`,
                           `context_length`, `capabilities`, modalities).
  GET /api/providers       Active connections (id, provider, label,
                           isActive, priority, createdAt, updatedAt).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import ValidationError

from omni_route_config.types import ModelEntry, ModelType, ProviderRegistry

# Default cache lives next to the existing `.omniroute/` directory used by
# bootstrap for the npx PID file. Same path semantics: per-cwd, gitignored.
_CACHE_DIR = Path(".omniroute")
_CACHE_FILE = _CACHE_DIR / "registry.json"
_DEFAULT_TTL = timedelta(hours=24)

_VALID_TYPES: set[str] = {
    "chat",
    "embedding",
    "image",
    "audio",
    "rerank",
    "moderation",
    "video",
    "music",
}


def _base_url() -> str:
    return os.environ.get("OMNIROUTE_URL", "http://localhost:20128").rstrip("/")


def _bearer_headers() -> dict[str, str]:
    tok = os.environ.get("OMNIROUTE_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _classify(raw: dict[str, Any]) -> ModelType:
    """Map an /api/v1/models entry to one of our ModelType literals.

    OmniRoute's catalog returns chat models WITHOUT an explicit `type`
    field (they're the implicit default). Embeddings / images / audio /
    rerank / etc all set `type` explicitly. So: anything missing or
    unrecognized → 'chat'.
    """
    t = raw.get("type")
    if isinstance(t, str) and t in _VALID_TYPES:
        return cast(ModelType, t)
    return "chat"


def _to_model_entry(raw: dict[str, Any]) -> ModelEntry | None:
    model_id = raw.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    provider = raw.get("owned_by") or raw.get("provider") or raw.get("root") or "unknown"
    if not isinstance(provider, str):
        provider = str(provider)
    try:
        return ModelEntry(
            id=model_id,
            provider=provider,
            type=_classify(raw),
            subtype=raw.get("subtype") if isinstance(raw.get("subtype"), str) else None,
            context_length=raw.get("context_length")
            if isinstance(raw.get("context_length"), int)
            else None,
            capabilities=raw.get("capabilities")
            if isinstance(raw.get("capabilities"), dict)
            else {},
            input_modalities=list(raw.get("input_modalities") or []),
            output_modalities=list(raw.get("output_modalities") or []),
            custom=bool(raw.get("custom", False)),
            api_format=raw.get("api_format") if isinstance(raw.get("api_format"), str) else None,
        )
    except ValidationError:
        return None


async def _fetch_models(client: httpx.AsyncClient, base: str) -> list[ModelEntry]:
    resp = await client.get(f"{base}/api/v1/models")
    resp.raise_for_status()
    body = resp.json() or {}
    raw_list = body.get("data") if isinstance(body, dict) else None
    if not isinstance(raw_list, list):
        return []
    out: list[ModelEntry] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        entry = _to_model_entry(raw)
        if entry is not None:
            out.append(entry)
    return out


async def _fetch_connections(client: httpx.AsyncClient, base: str) -> list[dict[str, Any]]:
    resp = await client.get(f"{base}/api/providers")
    resp.raise_for_status()
    body = resp.json() or {}
    if isinstance(body, dict):
        conns = body.get("connections") or []
        if isinstance(conns, list):
            return [c for c in conns if isinstance(c, dict)]
    return []


async def fetch_registry(
    *,
    base_url: str | None = None,
    timeout: float = 15.0,
) -> ProviderRegistry:
    """Fetch the live registry from OmniRoute. Never reads cache."""
    base = (base_url or _base_url()).rstrip("/")
    async with httpx.AsyncClient(timeout=timeout, headers=_bearer_headers()) as client:
        models = await _fetch_models(client, base)
        conns = await _fetch_connections(client, base)

    by_provider: dict[str, list[ModelEntry]] = {}
    for m in models:
        by_provider.setdefault(m.provider, []).append(m)
    for c in conns:
        pid = c.get("provider")
        if isinstance(pid, str):
            by_provider.setdefault(pid, [])

    return ProviderRegistry(
        base_url=base,
        fetched_at=datetime.now(tz=UTC),
        providers=by_provider,
        connections=conns,
    )


def load_cached(
    *,
    cache_path: Path | None = None,
    ttl: timedelta = _DEFAULT_TTL,
) -> ProviderRegistry | None:
    """Return a cached registry if it exists and is within TTL, else None."""
    p = cache_path or _CACHE_FILE
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        reg = ProviderRegistry.model_validate(raw)
    except (json.JSONDecodeError, ValidationError, OSError):
        return None
    if datetime.now(tz=UTC) - reg.fetched_at > ttl:
        return None
    return reg


def save_cache(reg: ProviderRegistry, *, cache_path: Path | None = None) -> Path:
    p = cache_path or _CACHE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = reg.model_dump(mode="json")
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p


async def get_registry(
    *,
    use_cache: bool = True,
    base_url: str | None = None,
    cache_path: Path | None = None,
    ttl: timedelta = _DEFAULT_TTL,
) -> ProviderRegistry:
    """Return the registry. Cache → live fetch fallback.

    `use_cache=False` forces a live fetch and refreshes the cache.
    """
    if use_cache:
        cached = load_cached(cache_path=cache_path, ttl=ttl)
        if cached is not None:
            return cached
    reg = await fetch_registry(base_url=base_url)
    save_cache(reg, cache_path=cache_path)
    return reg
