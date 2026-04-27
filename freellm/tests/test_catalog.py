from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from freellm import (
    PROVIDERS,
    AllProvidersExhaustedError,
    call_text,
    list_providers,
    plan,
    quotas,
)
from freellm.schemas import ALL_MODALITIES, ProviderEntry

# ---------- catalog integrity ----------


def test_catalog_covers_every_modality():
    for modality in ALL_MODALITIES:
        assert modality in PROVIDERS, f"modality {modality!r} missing"
        assert len(PROVIDERS[modality]) >= 1, f"modality {modality!r} has no entries"


def test_every_entry_validates_as_provider_entry():
    for entries in PROVIDERS.values():
        for e in entries:
            assert isinstance(e, ProviderEntry)
            assert e.provider
            assert e.model
            assert e.env_var.endswith("_KEY") or e.env_var.endswith("_TOKEN")
            assert e.last_verified is not None


def test_no_duplicate_provider_model_pair_within_modality():
    for modality, entries in PROVIDERS.items():
        seen: set[tuple[str, str]] = set()
        for e in entries:
            key = (e.provider, e.model)
            assert key not in seen, (
                f"duplicate ({e.provider}, {e.model}) within {modality}"
            )
            seen.add(key)


def test_list_providers_no_arg_returns_all():
    rows = list_providers()
    expected = sum(len(v) for v in PROVIDERS.values())
    assert len(rows) == expected


def test_list_providers_modality_filter():
    rows = list_providers("text")
    assert len(rows) == len(PROVIDERS["text"])
    assert all(r.model for r in rows)


# ---------- plan() ----------


def test_plan_with_no_keys_skips_everything():
    # Ensure no provider keys leak from the host env.
    saved = {}
    for key in {e.env_var for entries in PROVIDERS.values() for e in entries}:
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    try:
        p = plan(modality="text", task_name="test-empty")
        assert p.modality == "text"
        assert p.options == []
        assert p.chosen is None
        assert len(p.reason_skipped) == len(PROVIDERS["text"])
        for reason in p.reason_skipped.values():
            assert "missing env var" in reason
    finally:
        os.environ.update(saved)


def test_plan_with_groq_key_picks_groq_first(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key-not-used")
    p = plan(modality="text", task_name="test-with-key")
    assert p.chosen is not None
    assert p.chosen.provider == "groq"
    assert p.chosen.env_var_present is True


def test_plan_dry_run_via_call_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake")
    result = asyncio.run(
        call_text(
            messages=[{"role": "user", "content": "hi"}],
            task_name="dry-run-test",
            dry_run=True,
        )
    )
    # dry_run returns Plan, not Result
    assert hasattr(result, "options")
    assert result.chosen.provider == "groq"


def test_call_text_runtime_not_yet_implemented(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake")
    with pytest.raises(NotImplementedError):
        asyncio.run(
            call_text(
                messages=[{"role": "user", "content": "hi"}],
                task_name="runtime-test",
                dry_run=False,
            )
        )


# ---------- quotas ----------


def test_quotas_save_and_load_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FREELLM_QUOTA_DIR", str(tmp_path))
    state = quotas.load()
    assert state.entries == {}
    quotas.record_success(
        state, provider="groq", model="llama-3.3-70b-versatile", tokens_in=10, tokens_out=20
    )
    quotas.save(state)
    reloaded = quotas.load()
    key = quotas.key_of("groq", "llama-3.3-70b-versatile")
    assert key in reloaded.entries
    assert reloaded.entries[key].requests_used == 1
    assert reloaded.entries[key].tokens_used == 30


def test_record_failure_disables_after_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FREELLM_QUOTA_DIR", str(tmp_path))
    state = quotas.load()
    for _ in range(3):
        quotas.record_failure(
            state, provider="cerebras", model="llama3.1-70b", reason="429"
        )
    usage = quotas.get(state, "cerebras", "llama3.1-70b")
    assert usage.consecutive_failures == 3
    assert usage.disabled_until is not None
    assert quotas.is_disabled(usage)


# ---------- AllProvidersExhaustedError ----------


def test_all_providers_exhausted_error_carries_chain():
    err = AllProvidersExhaustedError(["groq/llama-3.3", "gemini/flash"])
    assert err.chain_attempted == ["groq/llama-3.3", "gemini/flash"]
    assert "groq/llama-3.3" in str(err)
