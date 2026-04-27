"""Bootstrap + apply_config tests against a mocked OmniRoute (respx)."""

from __future__ import annotations

import httpx
import respx

from omni_route_config import bootstrap
from omni_route_config.catalog import ProviderCatalog, ProviderEntry


@respx.mock
async def test_status_reachable_returns_provider_count(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/init").mock(
        return_value=httpx.Response(200, json={"initialized": True, "version": "3.7.1"})
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(
            200, json={"connections": [{"id": "x"}, {"id": "y"}]}
        )
    )
    s = await bootstrap.status()
    assert s.reachable is True
    assert s.providers_configured == 2
    assert s.version == "3.7.1"


@respx.mock
async def test_status_unreachable(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/init").mock(side_effect=httpx.ConnectError("nope"))
    respx.get("http://omni.test/").mock(side_effect=httpx.ConnectError("nope"))
    s = await bootstrap.status()
    assert s.reachable is False
    assert s.providers_configured == 0


@respx.mock
async def test_apply_config_posts_runnable_entries(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    posted: list[dict] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        import json

        posted.append(json.loads(request.content))
        return httpx.Response(201, json={"connection": {"id": "abc"}})

    respx.post("http://omni.test/api/providers").mock(side_effect=_capture)

    cat = ProviderCatalog(
        providers=[
            ProviderEntry(
                provider="groq",
                env_var="GROQ_API_KEY",
                priority=10,
                name="Groq Test",
                default_model="llama-3.3-70b-versatile",
            ),
            ProviderEntry(
                provider="gemini",
                env_var="GEMINI_API_KEY",
                priority=20,
            ),
        ]
    )
    result = await bootstrap.apply_config(cat)

    assert result.total == 2
    assert result.applied == 1
    assert result.skipped_missing_key == 1
    assert result.errors == 0
    assert len(posted) == 1
    assert posted[0]["provider"] == "groq"
    assert posted[0]["apiKey"] == "gsk_fake"
    assert posted[0]["priority"] == 10
    assert posted[0]["name"] == "Groq Test"
    assert posted[0]["defaultModel"] == "llama-3.3-70b-versatile"


@respx.mock
async def test_apply_config_handles_already_present(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    monkeypatch.setenv("X_KEY", "v")
    respx.post("http://omni.test/api/providers").mock(
        return_value=httpx.Response(409, json={"error": "already exists"})
    )
    cat = ProviderCatalog(
        providers=[ProviderEntry(provider="x", env_var="X_KEY")]
    )
    result = await bootstrap.apply_config(cat)
    assert result.already_present == 1
    assert result.applied == 0


@respx.mock
async def test_apply_config_records_http_errors(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    monkeypatch.setenv("X_KEY", "v")
    respx.post("http://omni.test/api/providers").mock(
        return_value=httpx.Response(500, text="boom")
    )
    cat = ProviderCatalog(
        providers=[ProviderEntry(provider="x", env_var="X_KEY")]
    )
    result = await bootstrap.apply_config(cat)
    assert result.errors == 1
    assert result.items[0].status == "error"
    assert "500" in (result.items[0].detail or "")


@respx.mock
async def test_apply_config_passes_provider_specific_data(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    monkeypatch.setenv("X_KEY", "v")
    posted: list[dict] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        import json

        posted.append(json.loads(request.content))
        return httpx.Response(201, json={"connection": {"id": "id"}})

    respx.post("http://omni.test/api/providers").mock(side_effect=_capture)
    cat = ProviderCatalog(
        providers=[
            ProviderEntry(
                provider="x",
                env_var="X_KEY",
                provider_specific_data={"region": "us"},
            )
        ]
    )
    await bootstrap.apply_config(cat)
    assert posted[0]["providerSpecificData"] == {"region": "us"}


@respx.mock
async def test_ensure_running_returns_existing_when_reachable(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/init").mock(
        return_value=httpx.Response(200, json={"initialized": True, "version": "3.7.1"})
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    s = await bootstrap.ensure_running(prefer=("existing",))
    assert s.reachable is True
    assert s.version == "3.7.1"
