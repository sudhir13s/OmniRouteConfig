"""CLI smoke tests."""

from __future__ import annotations

import io
import json
import shutil
from contextlib import redirect_stdout
from datetime import UTC, datetime

import httpx
import pytest
import respx

from omni_route_config.cli import main
from omni_route_config.types import ModelEntry, ProviderRegistry

# Env vars in the bundled catalog. Wiped per test so a developer's real shell
# keys don't leak into apply_config() and produce real POSTs.
_CATALOG_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ASSEMBLYAI_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "CARTESIA_API_KEY",
    "CEREBRAS_API_KEY",
    "CLAUDE_CONSOLE_API_KEY",
    "COHERE_API_KEY",
    "DEEPGRAM_API_KEY",
    "DEEPSEEK_API_KEY",
    "ELEVENLABS_API_KEY",
    "EXA_API_KEY",
    "FIREWORKS_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "HF_TOKEN",
    "MISTRAL_API_KEY",
    "NVIDIA_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "SERPER_API_KEY",
    "TAVILY_API_KEY",
    "TOGETHER_API_KEY",
)


@pytest.fixture
def clean_env(monkeypatch):
    for k in _CATALOG_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("OMNIROUTE_API_TOKEN", raising=False)
    return monkeypatch


def test_cli_version():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["version"])
    assert rc == 0
    assert json.loads(buf.getvalue())["version"]


def test_cli_catalog_with_explicit_path(tmp_path):
    yaml = tmp_path / "c.yaml"
    yaml.write_text(
        "version: 1\nproviders:\n  - provider: groq\n    env_var: GROQ_API_KEY\n",
        encoding="utf-8",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["catalog", "--path", str(yaml)])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["providers"][0]["provider"] == "groq"


def test_cli_catalog_default_path():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["catalog"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert any(p["provider"] == "groq" for p in out["providers"])


@respx.mock
def test_cli_status_unreachable_exits_2(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/init").mock(side_effect=httpx.ConnectError("x"))
    respx.get("http://omni.test/").mock(side_effect=httpx.ConnectError("x"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["status"])
    assert rc == 2
    payload = json.loads(buf.getvalue())
    assert payload["reachable"] is False


@respx.mock
def test_cli_status_reachable_exits_0(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/init").mock(
        return_value=httpx.Response(200, json={"initialized": True, "version": "3.7.1"})
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["status"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["reachable"] is True


@respx.mock
def test_cli_init_reachable_exits_0(clean_env):
    clean_env.setenv("OMNIROUTE_URL", "http://omni.test")
    respx.get("http://omni.test/api/init").mock(
        return_value=httpx.Response(200, json={"initialized": True, "version": "3.7.1"})
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": []})
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["init"])
    assert rc == 0
    assert json.loads(buf.getvalue())["reachable"] is True


@respx.mock
def test_cli_init_unreachable_exits_2(clean_env):
    clean_env.setenv("OMNIROUTE_URL", "http://omni.test")
    # ensure_running tries existing→npx→docker. With no npx/docker mocks and
    # connection error on probes, all strategies fail fast (timeout shrunk).
    respx.get("http://omni.test/api/init").mock(side_effect=httpx.ConnectError("x"))
    respx.get("http://omni.test/").mock(side_effect=httpx.ConnectError("x"))

    # Stop ensure_running from spending real time spawning npx/docker.
    import omni_route_config.cli as cli_mod

    async def _fast_unreachable(**kwargs):
        from omni_route_config.types import OmniRouteStatus

        return OmniRouteStatus(base_url="http://omni.test", reachable=False, detail="forced")

    clean_env.setattr(cli_mod, "ensure_running", _fast_unreachable)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["init", "--timeout", "1"])
    assert rc == 2
    assert json.loads(buf.getvalue())["reachable"] is False


@respx.mock
def test_cli_configure_no_keys_set_exits_0(clean_env):
    """No env vars set → all 21 catalog entries marked skipped_missing_key.
    No POSTs happen, errors=0, rc=0."""
    clean_env.setenv("OMNIROUTE_URL", "http://omni.test")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["configure"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["errors"] == 0
    assert payload["applied"] == 0
    assert payload["skipped_missing_key"] >= 1
    # No POSTs were made because no env keys were set.
    assert not respx.routes


@respx.mock
def test_cli_configure_http_error_exits_3(clean_env):
    clean_env.setenv("OMNIROUTE_URL", "http://omni.test")
    clean_env.setenv("GROQ_API_KEY", "test-groq-key")
    respx.post("http://omni.test/api/providers").mock(return_value=httpx.Response(500, text="boom"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["configure"])
    assert rc == 3
    payload = json.loads(buf.getvalue())
    assert payload["errors"] >= 1


def test_cli_down_calls_tear_down(monkeypatch):
    import omni_route_config.cli as cli_mod

    calls: list[str] = []
    monkeypatch.setattr(cli_mod, "tear_down", lambda: calls.append("td") or True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["down"])
    assert rc == 0
    assert calls == ["td"]
    assert json.loads(buf.getvalue())["stopped"] is True


def test_cli_destroy_without_yes_exits_6(capsys):
    rc = main(["destroy"])
    assert rc == 6
    err = capsys.readouterr().err
    assert "--yes" in err


def test_cli_destroy_with_yes_calls_volume_remove(monkeypatch):
    import omni_route_config.cli as cli_mod

    calls: list[str] = []
    monkeypatch.setattr(cli_mod, "tear_down", lambda: calls.append("td") or True)
    monkeypatch.setattr(cli_mod, "destroy_volume", lambda: calls.append("dv") or True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["destroy", "--yes"])
    assert rc == 0
    assert calls == ["td", "dv"]
    assert json.loads(buf.getvalue())["volume_removed"] is True


def test_cli_env_sync_writes_dotenv(clean_env, tmp_path):
    clean_env.setenv("GROQ_API_KEY", "shell-groq")
    out = tmp_path / ".env"
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["env-sync", "--path", str(out)])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["wrote"] == str(out)
    assert "GROQ_API_KEY" in payload["provider_keys_from_shell"]
    # Server secrets generated on first run.
    assert "JWT_SECRET" in payload["secrets_generated"]
    contents = out.read_text(encoding="utf-8")
    assert "GROQ_API_KEY=shell-groq" in contents
    assert "JWT_SECRET=" in contents


@respx.mock
def test_cli_doctor_returns_audit(clean_env, tmp_path, monkeypatch):
    """doctor exits 0 when reachable, 2 when neither reachable nor container running."""
    clean_env.setenv("OMNIROUTE_URL", "http://omni.test")
    clean_env.setenv("GROQ_API_KEY", "shell-groq")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=in-dotenv\n", encoding="utf-8")

    import omni_route_config.cli as cli_mod

    monkeypatch.setattr(cli_mod, "_docker_inspect_state", lambda _name: None)
    respx.get("http://omni.test/api/init").mock(
        return_value=httpx.Response(200, json={"initialized": True, "version": "3.7.1"})
    )
    respx.get("http://omni.test/api/providers").mock(
        return_value=httpx.Response(200, json={"connections": [{"id": "1"}]})
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["doctor", "--path", str(env_file)])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["dotenv_path"] == str(env_file)
    assert payload["dotenv_exists"] is True
    assert "OPENAI_API_KEY" in payload["provider_keys_in_dotenv"]
    assert "GROQ_API_KEY" in payload["provider_keys_in_shell_only"]
    assert "JWT_SECRET" in payload["server_secrets_missing"]
    assert payload["docker"]["state"] is None
    assert payload["reachable"] is True
    assert payload["providers_configured"] == 1


@respx.mock
def test_cli_doctor_unreachable_no_container_exits_2(clean_env, tmp_path, monkeypatch):
    clean_env.setenv("OMNIROUTE_URL", "http://omni.test")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    import omni_route_config.cli as cli_mod

    monkeypatch.setattr(cli_mod, "_docker_inspect_state", lambda _name: None)
    respx.get("http://omni.test/api/init").mock(side_effect=httpx.ConnectError("x"))
    respx.get("http://omni.test/").mock(side_effect=httpx.ConnectError("x"))

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["doctor", "--path", str(env_file)])
    assert rc == 2
    payload = json.loads(buf.getvalue())
    assert payload["reachable"] is False


@respx.mock
def test_cli_up_full_flow(clean_env, tmp_path, monkeypatch):
    """up → env-sync writes .env, ensure_running returns reachable, apply_config
    runs against the catalog with no env keys → applied=0, errors=0, rc=0."""
    clean_env.setenv("OMNIROUTE_URL", "http://omni.test")
    env_file = tmp_path / ".env"

    import omni_route_config.cli as cli_mod
    from omni_route_config.types import OmniRouteStatus

    async def _reachable(**kwargs):
        return OmniRouteStatus(
            base_url="http://omni.test",
            reachable=True,
            version="3.7.1",
            providers_configured=0,
        )

    monkeypatch.setattr(cli_mod, "ensure_running", _reachable)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["up", "--path", str(env_file), "--timeout", "1"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["ok"] is True
    assert payload["env_sync"]["wrote"] == str(env_file)
    assert payload["status"]["reachable"] is True
    assert payload["apply"]["errors"] == 0
    assert env_file.exists()


def test_cli_up_unreachable_exits_2(clean_env, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"

    import omni_route_config.cli as cli_mod
    from omni_route_config.types import OmniRouteStatus

    async def _unreachable(**kwargs):
        return OmniRouteStatus(base_url="http://omni.test", reachable=False, detail="forced")

    monkeypatch.setattr(cli_mod, "ensure_running", _unreachable)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["up", "--path", str(env_file), "--timeout", "1"])
    assert rc == 2
    payload = json.loads(buf.getvalue())
    assert payload["ok"] is False
    assert env_file.exists()  # env-sync ran before ensure_running failed


def test_cli_smoke_test_missing_extra_exits_4(monkeypatch, capsys):
    """If openai SDK isn't importable the smoke command exits 4."""
    import sys

    # Force the import-from-omni_route_config.client path to raise ImportError
    # by replacing the module in sys.modules with a sentinel that has no
    # `openai_for_omniroute` attribute.
    fake = type(sys)("omni_route_config.client")
    monkeypatch.setitem(sys.modules, "omni_route_config.client", fake)
    rc = main(["smoke-test"])
    assert rc == 4
    out = capsys.readouterr().out
    assert "openai_for_omniroute" in out or "error" in out


# ---------------------------------------------------------------------------
# helpers shared by models + sync tests
# ---------------------------------------------------------------------------


def _make_registry() -> ProviderRegistry:
    return ProviderRegistry(
        base_url="http://omni.test",
        fetched_at=datetime.now(tz=UTC),
        providers={
            "groq": [
                ModelEntry(id="llama-3.3-70b", provider="groq"),
                ModelEntry(id="mixtral-8x7b", provider="groq"),
            ],
            "openai": [
                ModelEntry(
                    id="text-embedding-3-large",
                    provider="openai",
                    type="embedding",
                ),
            ],
        },
    )


# ---------------------------------------------------------------------------
# models subcommand
# ---------------------------------------------------------------------------


def test_cli_models_basic_output(monkeypatch):
    async def _fake_registry(**kwargs):
        return _make_registry()

    monkeypatch.setattr("omni_route_config.cli.get_registry", _fake_registry)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["models"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["model_count"] == 3
    assert "groq" in payload["providers"]
    assert "openai" in payload["providers"]


def test_cli_models_filter_by_type(monkeypatch):
    async def _fake_registry(**kwargs):
        return _make_registry()

    monkeypatch.setattr("omni_route_config.cli.get_registry", _fake_registry)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["models", "--type", "embedding"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["model_count"] == 1
    assert "openai" in payload["providers"]
    assert "groq" not in payload["providers"]


def test_cli_models_filter_by_provider(monkeypatch):
    async def _fake_registry(**kwargs):
        return _make_registry()

    monkeypatch.setattr("omni_route_config.cli.get_registry", _fake_registry)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["models", "--provider", "groq"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["model_count"] == 2
    assert "groq" in payload["providers"]
    assert "openai" not in payload["providers"]


def test_cli_models_no_cache_flag_passed_through(monkeypatch):
    received: dict = {}

    async def _fake_registry(**kwargs):
        received.update(kwargs)
        return _make_registry()

    monkeypatch.setattr("omni_route_config.cli.get_registry", _fake_registry)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["models", "--no-cache"])
    assert rc == 0
    assert received.get("use_cache") is False


def test_cli_models_returns_2_on_fetch_error(monkeypatch):
    async def _failing(**kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("omni_route_config.cli.get_registry", _failing)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["models"])
    assert rc == 2
    payload = json.loads(buf.getvalue())
    assert "error" in payload
    assert "detail" in payload


# ---------------------------------------------------------------------------
# sync subcommand
# ---------------------------------------------------------------------------


def test_cli_sync_dry_run_reports_diff(monkeypatch):
    """Remote has brand-new-one (not in YAML); YAML has catalog-only providers."""

    async def _fake_registry(**kwargs):
        # groq + gemini are in the bundled YAML; brand-new-one is not
        return ProviderRegistry(
            base_url="http://omni.test",
            fetched_at=datetime.now(tz=UTC),
            providers={
                "groq": [ModelEntry(id="llama-3.3-70b", provider="groq")],
                "gemini": [ModelEntry(id="gemini-pro", provider="gemini")],
                "brand-new-one": [],
            },
        )

    monkeypatch.setattr("omni_route_config.cli.get_registry", _fake_registry)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["sync"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["wrote"] is None
    assert "brand-new-one" in payload["in_remote_only"]
    # The bundled YAML has many more providers than groq+gemini
    assert len(payload["in_yaml_only"]) > 0


def test_cli_sync_with_write_appends_new_rows(monkeypatch, tmp_path):
    from omni_route_config.catalog import DEFAULT_CATALOG_PATH

    tmp_yaml = tmp_path / "free-providers.yaml"
    shutil.copy(DEFAULT_CATALOG_PATH, tmp_yaml)

    async def _fake_registry(**kwargs):
        return ProviderRegistry(
            base_url="http://omni.test",
            fetched_at=datetime.now(tz=UTC),
            providers={
                "groq": [ModelEntry(id="llama-3.3-70b", provider="groq")],
                "brand-new-one": [],
            },
        )

    monkeypatch.setattr("omni_route_config.cli.get_registry", _fake_registry)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["sync", "--path", str(tmp_yaml), "--write"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["wrote"] == str(tmp_yaml)
    contents = tmp_yaml.read_text(encoding="utf-8")
    assert "provider: brand-new-one" in contents
    assert "BRAND_NEW_ONE_API_KEY" in contents
    # Original rows still present
    assert "provider: groq" in contents


def test_cli_sync_write_no_op_when_no_additions(monkeypatch, tmp_path):
    from omni_route_config.catalog import DEFAULT_CATALOG_PATH, load_catalog

    tmp_yaml = tmp_path / "free-providers.yaml"
    shutil.copy(DEFAULT_CATALOG_PATH, tmp_yaml)

    # Build a registry whose provider ids exactly match the YAML
    cat = load_catalog(str(tmp_yaml))
    yaml_ids = {e.provider for e in cat.providers}

    async def _fake_registry(**kwargs):
        return ProviderRegistry(
            base_url="http://omni.test",
            fetched_at=datetime.now(tz=UTC),
            providers={pid: [] for pid in yaml_ids},
        )

    monkeypatch.setattr("omni_route_config.cli.get_registry", _fake_registry)
    original = tmp_yaml.read_text(encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["sync", "--path", str(tmp_yaml), "--write"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["wrote"] is None
    assert "no addition" in (payload.get("reason") or "").lower()
    # File must be untouched
    assert tmp_yaml.read_text(encoding="utf-8") == original


def test_cli_sync_returns_2_on_fetch_error(monkeypatch):
    async def _failing(**kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("omni_route_config.cli.get_registry", _failing)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["sync"])
    assert rc == 2
    payload = json.loads(buf.getvalue())
    assert "error" in payload
