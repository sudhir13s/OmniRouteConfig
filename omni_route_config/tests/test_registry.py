"""Registry fetch, cache, and get_registry tests against a mocked OmniRoute."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from omni_route_config.registry import fetch_registry, get_registry, load_cached, save_cache
from omni_route_config.types import ModelEntry, ProviderRegistry

# ---------------------------------------------------------------------------
# Shared mock payloads
# ---------------------------------------------------------------------------

_MODELS_RESP = {
    "data": [
        {"id": "llama-3-8b", "owned_by": "groq"},
        {"id": "mixtral-8x7b", "owned_by": "groq"},
        {"id": "gemini-pro", "owned_by": "gemini"},
    ]
}

_PROVIDERS_RESP = {
    "connections": [
        {"id": "1", "provider": "groq", "label": "Groq", "isActive": True},
        {"id": "2", "provider": "gemini", "label": "Gemini", "isActive": True},
    ]
}


# ---------------------------------------------------------------------------
# Test 1: grouping by provider
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_registry_groups_models_by_provider(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/v1/models").mock(
        return_value=httpx.Response(200, json=_MODELS_RESP)
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json=_PROVIDERS_RESP)
    )

    reg = await fetch_registry()

    assert set(reg.providers.keys()) == {"groq", "gemini"}
    assert len(reg.providers["groq"]) == 2
    assert len(reg.providers["gemini"]) == 1
    assert reg.model_count() == 3
    assert all(m.provider == "groq" for m in reg.providers["groq"])


# ---------------------------------------------------------------------------
# Test 2: type classification
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_registry_classifies_by_type(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    models_resp = {
        "data": [
            {"id": "chat-model", "owned_by": "p"},
            {"id": "emb-model", "owned_by": "p", "type": "embedding", "dimensions": 1024},
            {"id": "img-model", "owned_by": "p", "type": "image"},
            {"id": "aud-model", "owned_by": "p", "type": "audio", "subtype": "transcription"},
            {"id": "rnk-model", "owned_by": "p", "type": "rerank"},
            {"id": "mod-model", "owned_by": "p", "type": "moderation"},
            {"id": "unk-model", "owned_by": "p", "type": "video-foo"},
        ]
    }
    respx.get("http://omni.test/api/v1/models").mock(
        return_value=httpx.Response(200, json=models_resp)
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )

    reg = await fetch_registry()
    models = {m.id: m for m in reg.providers["p"]}

    assert models["chat-model"].type == "chat"
    assert models["emb-model"].type == "embedding"
    assert models["img-model"].type == "image"
    assert models["aud-model"].type == "audio"
    assert models["aud-model"].subtype == "transcription"
    assert models["rnk-model"].type == "rerank"
    assert models["mod-model"].type == "moderation"
    assert models["unk-model"].type == "chat"  # unknown → safe default


# ---------------------------------------------------------------------------
# Test 3: capabilities and modalities round-trip
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_registry_handles_capabilities_and_modalities(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    models_resp = {
        "data": [
            {
                "id": "vision-model",
                "owned_by": "p",
                "context_length": 200000,
                "capabilities": {"vision": True},
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            }
        ]
    }
    respx.get("http://omni.test/api/v1/models").mock(
        return_value=httpx.Response(200, json=models_resp)
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )

    reg = await fetch_registry()
    m = reg.providers["p"][0]

    assert m.context_length == 200000
    assert m.capabilities == {"vision": True}
    assert m.input_modalities == ["text", "image"]
    assert m.output_modalities == ["text"]


# ---------------------------------------------------------------------------
# Test 4: invalid rows are dropped
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_registry_drops_invalid_rows(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    models_resp = {
        "data": [
            {"id": "good-model", "owned_by": "p"},
            {"owned_by": "p"},  # missing id
            "not-a-dict",  # wrong shape
        ]
    }
    respx.get("http://omni.test/api/v1/models").mock(
        return_value=httpx.Response(200, json=models_resp)
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )

    reg = await fetch_registry()

    assert reg.model_count() == 1
    assert reg.providers["p"][0].id == "good-model"


# ---------------------------------------------------------------------------
# Test 5: provider with no models still appears if in connections
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_registry_includes_providers_with_no_models(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(
            200, json={"connections": [{"id": "1", "provider": "cerebras", "isActive": True}]}
        )
    )

    reg = await fetch_registry()

    assert "cerebras" in reg.providers
    assert reg.providers["cerebras"] == []


# ---------------------------------------------------------------------------
# Test 6: HTTP 500 on /api/v1/models propagates
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_registry_propagates_http_error(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/v1/models").mock(return_value=httpx.Response(500))
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_registry()


# ---------------------------------------------------------------------------
# Test 7: save_cache / load_cached round-trip
# ---------------------------------------------------------------------------


async def test_save_cache_and_load_cached_round_trip(tmp_path):
    reg = ProviderRegistry(
        base_url="http://omni.test",
        fetched_at=datetime.now(tz=UTC),
        providers={"groq": [ModelEntry(id="llama-3-8b", provider="groq")]},
        connections=[],
    )
    cache_path = tmp_path / "registry.json"
    save_cache(reg, cache_path=cache_path)

    loaded = load_cached(cache_path=cache_path)

    assert loaded is not None
    assert loaded.model_count() == reg.model_count()
    assert loaded.base_url == reg.base_url


# ---------------------------------------------------------------------------
# Test 8: expired cache returns None
# ---------------------------------------------------------------------------


async def test_load_cached_returns_none_when_expired(tmp_path):
    reg = ProviderRegistry(
        base_url="http://omni.test",
        fetched_at=datetime.now(tz=UTC) - timedelta(days=2),
        providers={},
        connections=[],
    )
    cache_path = tmp_path / "registry.json"
    save_cache(reg, cache_path=cache_path)

    result = load_cached(cache_path=cache_path, ttl=timedelta(hours=24))

    assert result is None


# ---------------------------------------------------------------------------
# Test 9: missing path returns None
# ---------------------------------------------------------------------------


async def test_load_cached_returns_none_when_missing(tmp_path):
    result = load_cached(cache_path=tmp_path / "nonexistent.json")
    assert result is None


# ---------------------------------------------------------------------------
# Test 10: corrupt JSON returns None
# ---------------------------------------------------------------------------


async def test_load_cached_returns_none_on_corrupt_json(tmp_path):
    cache_path = tmp_path / "registry.json"
    cache_path.write_text("{ this is not valid json !!!", encoding="utf-8")

    result = load_cached(cache_path=cache_path)

    assert result is None


# ---------------------------------------------------------------------------
# Test 11: get_registry uses cache when fresh (no network call)
# ---------------------------------------------------------------------------


async def test_get_registry_uses_cache_when_fresh(tmp_path):
    reg = ProviderRegistry(
        base_url="http://omni.test",
        fetched_at=datetime.now(tz=UTC),
        providers={"groq": [ModelEntry(id="llama-3-8b", provider="groq")]},
        connections=[],
    )
    cache_path = tmp_path / "registry.json"
    save_cache(reg, cache_path=cache_path)

    # No respx mock — any real network call would raise
    result = await get_registry(use_cache=True, cache_path=cache_path)

    assert result.model_count() == 1
    assert result.base_url == "http://omni.test"


# ---------------------------------------------------------------------------
# Test 12: get_registry bypasses cache when use_cache=False
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_registry_bypasses_cache_when_no_cache_true(monkeypatch, tmp_path):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    # Cache has stale data (different provider)
    stale = ProviderRegistry(
        base_url="http://omni.test",
        fetched_at=datetime.now(tz=UTC),
        providers={"stale-provider": []},
        connections=[],
    )
    cache_path = tmp_path / "registry.json"
    save_cache(stale, cache_path=cache_path)

    # Network returns fresh data
    respx.get("http://omni.test/api/v1/models").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "new-model", "owned_by": "fresh-provider"}]}
        )
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )

    result = await get_registry(use_cache=False, cache_path=cache_path)

    assert "fresh-provider" in result.providers
    assert "stale-provider" not in result.providers
    # Cache was refreshed
    reloaded = load_cached(cache_path=cache_path)
    assert reloaded is not None
    assert "fresh-provider" in reloaded.providers


# ---------------------------------------------------------------------------
# Test 13: bearer token is sent when OMNIROUTE_API_TOKEN is set
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_registry_sends_bearer_when_token_set(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    monkeypatch.setenv("OMNIROUTE_API_TOKEN", "my-tok")

    captured_auth: list[str] = []

    def _capture_models(request: httpx.Request) -> httpx.Response:
        captured_auth.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"data": []})

    def _capture_providers(request: httpx.Request) -> httpx.Response:
        captured_auth.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"connections": []})

    respx.get("http://omni.test/api/v1/models").mock(side_effect=_capture_models)
    respx.get("http://omni.test/api/providers").mock(side_effect=_capture_providers)

    await fetch_registry()

    assert len(captured_auth) == 2
    assert all(auth == "Bearer my-tok" for auth in captured_auth)
