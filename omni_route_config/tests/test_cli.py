"""CLI smoke tests."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import httpx
import respx

from omni_route_config.cli import main


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
    respx.get("http://omni.test/api/health").mock(side_effect=httpx.ConnectError("x"))
    respx.get("http://omni.test/api/version").mock(side_effect=httpx.ConnectError("x"))
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
    respx.get("http://omni.test/api/health").mock(
        return_value=httpx.Response(200, json={"version": "3.5.1"})
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
