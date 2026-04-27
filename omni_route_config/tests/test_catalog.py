"""Catalog parsing + filtering."""

from __future__ import annotations

import pytest

from omni_route_config.catalog import (
    DEFAULT_CATALOG_PATH,
    ProviderCatalog,
    ProviderEntry,
    env_var_present,
    filter_runnable,
    load_catalog,
)


def test_default_catalog_loads():
    cat = load_catalog()
    assert isinstance(cat, ProviderCatalog)
    assert cat.version == 1
    assert len(cat.providers) >= 5


def test_default_catalog_path_resolves_to_repo_file():
    assert DEFAULT_CATALOG_PATH.exists()


def test_load_catalog_explicit_path(tmp_path):
    yaml_path = tmp_path / "c.yaml"
    yaml_path.write_text(
        """
version: 1
providers:
  - provider: groq
    env_var: GROQ_API_KEY
    priority: 10
    name: G
""".strip(),
        encoding="utf-8",
    )
    cat = load_catalog(yaml_path)
    assert cat.providers[0].provider == "groq"
    assert cat.providers[0].priority == 10


def test_load_catalog_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_catalog(tmp_path / "no.yaml")


def test_load_catalog_via_env(tmp_path, monkeypatch):
    yaml_path = tmp_path / "c.yaml"
    yaml_path.write_text(
        "version: 1\nproviders:\n  - provider: x\n    env_var: X_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OMNI_ROUTE_CONFIG_PATH", str(yaml_path))
    cat = load_catalog()
    assert cat.providers[0].provider == "x"


# ---------- filtering ----------


def test_env_var_present_true_when_set(monkeypatch):
    monkeypatch.setenv("MY_KEY", "abc")
    e = ProviderEntry(provider="x", env_var="MY_KEY")
    assert env_var_present(e) is True


def test_env_var_present_false_when_unset(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    e = ProviderEntry(provider="x", env_var="MY_KEY")
    assert env_var_present(e) is False


def test_env_var_present_false_when_blank(monkeypatch):
    monkeypatch.setenv("MY_KEY", "   ")
    e = ProviderEntry(provider="x", env_var="MY_KEY")
    assert env_var_present(e) is False


def test_filter_runnable_excludes_disabled(monkeypatch):
    monkeypatch.setenv("K", "v")
    cat = ProviderCatalog(
        providers=[
            ProviderEntry(provider="a", env_var="K", enabled=True),
            ProviderEntry(provider="b", env_var="K", enabled=False),
        ]
    )
    runnable = filter_runnable(cat)
    assert {e.provider for e in runnable} == {"a"}


def test_filter_runnable_excludes_missing_keys(monkeypatch):
    monkeypatch.setenv("HAVE_KEY", "v")
    monkeypatch.delenv("MISSING_KEY", raising=False)
    cat = ProviderCatalog(
        providers=[
            ProviderEntry(provider="a", env_var="HAVE_KEY"),
            ProviderEntry(provider="b", env_var="MISSING_KEY"),
        ]
    )
    runnable = filter_runnable(cat)
    assert [e.provider for e in runnable] == ["a"]


# ---------- shape invariants on the bundled catalog ----------


def test_bundled_catalog_has_expected_high_priority_providers():
    cat = load_catalog()
    by_provider = {e.provider: e for e in cat.providers}
    # We commit to these living in the bundle.
    for must in ("groq", "gemini", "cerebras", "openrouter"):
        assert must in by_provider, f"{must} missing from bundled catalog"


def test_bundled_catalog_priorities_are_unique_within_modality_neighborhood():
    """Lower-priority providers should not all collide on the same number;
    sanity check the bundle uses distinct priorities."""
    cat = load_catalog()
    priorities = [e.priority for e in cat.providers]
    assert len(set(priorities)) >= max(3, len(priorities) // 2)
