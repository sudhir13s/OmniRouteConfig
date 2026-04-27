"""Tests for the config layer (programmatic API + YAML loader)."""

from __future__ import annotations

from datetime import date

import pytest

import freellm
from freellm import config as cfg_module


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts from the built-in catalog."""
    freellm.reset()
    yield
    freellm.reset()


# ---------- get_config / reset ----------


def test_get_config_starts_with_builtin_catalog():
    cfg = freellm.get_config()
    assert cfg.total_entries >= 28
    assert "text" in cfg.providers
    assert "groq" in {e.provider for e in cfg.providers["text"]}


def test_reset_drops_user_overrides():
    freellm.configure(disable=["groq"])
    assert "groq" not in {e.provider for e in freellm.get_config().providers["text"]}
    freellm.reset()
    assert "groq" in {e.provider for e in freellm.get_config().providers["text"]}


# ---------- configure: disable ----------


def test_configure_disable_drops_provider_from_every_modality():
    freellm.configure(disable=["replicate"])
    cfg = freellm.get_config()
    for entries in cfg.providers.values():
        assert "replicate" not in {e.provider for e in entries}
    assert "replicate" in cfg.disabled


def test_configure_disable_persists_across_calls():
    freellm.configure(disable=["replicate"])
    freellm.configure(order={"text": ["gemini", "groq"]})
    cfg = freellm.get_config()
    for entries in cfg.providers.values():
        assert "replicate" not in {e.provider for e in entries}


# ---------- configure: order ----------


def test_configure_order_surfaces_preferred_providers_first():
    freellm.configure(order={"text": ["gemini", "groq"]})
    text_entries = freellm.get_config().providers["text"]
    # First entries must be all gemini, then all groq, then everything else.
    providers = [e.provider for e in text_entries]
    first_gemini = providers.index("gemini")
    first_groq = providers.index("groq")
    last_groq = len(providers) - 1 - list(reversed(providers)).index("groq")
    assert all(p == "gemini" for p in providers[: first_groq])
    assert first_gemini < first_groq
    # All non-listed providers come after the last "groq".
    listed = {"gemini", "groq"}
    for p in providers[last_groq + 1 :]:
        assert p not in listed


def test_configure_order_unknown_modality_raises():
    with pytest.raises(ValueError, match="unknown modality"):
        freellm.configure(order={"not-a-modality": ["groq"]})  # type: ignore[arg-type]


# ---------- configure: extra_providers ----------


def test_configure_extra_provider_added_to_modality():
    freellm.configure(
        extra_providers={
            "text": [
                {
                    "provider": "myproxy",
                    "model": "my-llama-70b",
                    "env_var": "MY_PROXY_KEY",
                    "speed_tier": "fast",
                    "last_verified": date(2026, 4, 26),
                    "free_tier": {"kind": "rpm_rpd", "rpm": 60, "rpd": 100000},
                }
            ]
        }
    )
    text = freellm.get_config().providers["text"]
    matches = [e for e in text if e.provider == "myproxy"]
    assert len(matches) == 1
    assert matches[0].model == "my-llama-70b"
    assert matches[0].env_var == "MY_PROXY_KEY"


def test_configure_extra_provider_replaces_existing_provider_model_pair():
    # First add a custom row.
    freellm.configure(
        extra_providers={
            "text": [
                {
                    "provider": "myproxy",
                    "model": "v1",
                    "env_var": "K",
                    "speed_tier": "fast",
                    "last_verified": date(2026, 4, 26),
                    "free_tier": {"kind": "requests_per_day", "rpd": 100},
                }
            ]
        }
    )
    # Now overwrite with the same (provider, model) but a different RPD.
    freellm.configure(
        extra_providers={
            "text": [
                {
                    "provider": "myproxy",
                    "model": "v1",
                    "env_var": "K",
                    "speed_tier": "fast",
                    "last_verified": date(2026, 4, 26),
                    "free_tier": {"kind": "requests_per_day", "rpd": 999},
                }
            ]
        }
    )
    matches = [
        e
        for e in freellm.get_config().providers["text"]
        if (e.provider, e.model) == ("myproxy", "v1")
    ]
    assert len(matches) == 1
    assert matches[0].free_tier.rpd == 999  # type: ignore[attr-defined]


# ---------- list_providers reads from config ----------


def test_list_providers_reflects_disable():
    before = len(freellm.list_providers("video_gen"))
    freellm.configure(disable=["replicate"])
    after = len(freellm.list_providers("video_gen"))
    assert after < before


# ---------- YAML loader ----------


def test_load_from_yaml_disable_and_order(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    cfg_file = tmp_path / "freellm.yaml"
    cfg_file.write_text(
        """
disable:
  - replicate
order:
  text:
    - cerebras
    - groq
""".strip()
    )
    monkeypatch.delenv("FREELLM_CONFIG_PATH", raising=False)
    monkeypatch.setenv("FREELLM_CONFIG_PATH", str(cfg_file))
    cfg_module.load_from_yaml()  # explicit reload after env mutation

    cfg = freellm.get_config()
    assert "replicate" in cfg.disabled
    text_providers = [e.provider for e in cfg.providers["text"]]
    assert text_providers[0] == "cerebras"


def test_load_from_yaml_extra_provider(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    cfg_file = tmp_path / "freellm.yaml"
    cfg_file.write_text(
        """
extra_providers:
  text:
    - provider: myproxy
      model: my-llama-70b
      env_var: MY_PROXY_KEY
      speed_tier: fast
      last_verified: "2026-04-26"
      free_tier:
        kind: rpm_rpd
        rpm: 60
        rpd: 100000
""".strip()
    )
    monkeypatch.setenv("FREELLM_CONFIG_PATH", str(cfg_file))
    cfg_module.load_from_yaml()

    matches = [
        e
        for e in freellm.get_config().providers["text"]
        if e.provider == "myproxy"
    ]
    assert len(matches) == 1


def test_load_from_yaml_missing_file_raises(tmp_path):
    pytest.importorskip("yaml")
    with pytest.raises(FileNotFoundError):
        cfg_module.load_from_yaml(tmp_path / "does-not-exist.yaml")


# ---------- per-model rotation invariant ----------
# The catalog ships multiple models per provider where rate limits are
# per-model. Verify no provider has just one entry where multi-entry
# would help (regression guard against accidentally collapsing entries).


def test_groq_text_has_multiple_models_for_per_model_rotation():
    text = freellm.list_providers("text")
    groq_models = [e.model for e in text if e.provider == "groq"]
    assert len(groq_models) >= 3, (
        "Groq has per-model RPD; catalog should expose >=3 text models "
        "for effective rotation."
    )


def test_groq_stt_has_multiple_models_for_per_model_rotation():
    stt = freellm.list_providers("stt")
    groq_models = [e.model for e in stt if e.provider == "groq"]
    assert len(groq_models) >= 2


def test_gemini_text_has_multiple_models():
    text = freellm.list_providers("text")
    gemini_models = [e.model for e in text if e.provider == "gemini"]
    assert len(gemini_models) >= 2
