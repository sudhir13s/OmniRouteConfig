"""Persistent per-provider per-day quota tracker.

State is stored as JSON at `${FREELLM_QUOTA_DIR}/quotas.json` (defaults to
`data/freellm/quotas.json` relative to the cwd).

v0.2 will wire `record_attempt()` / `is_capped()` into `router.py` so the
chain skips providers that have already burned today's free allotment.
v0.1 ships read + write helpers + a `dump()` for the CLI.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def _quota_path() -> Path:
    base = os.environ.get("FREELLM_QUOTA_DIR")
    if base:
        return Path(base) / "quotas.json"
    return Path("data") / "freellm" / "quotas.json"


@dataclass
class ProviderUsage:
    date: str  # ISO YYYY-MM-DD
    requests_used: int = 0
    tokens_used: int = 0
    consecutive_failures: int = 0
    last_success_at: str | None = None
    last_failure_reason: str | None = None
    disabled_until: str | None = None  # ISO date


@dataclass
class QuotaState:
    """Top-level state file shape.

    Keyed by `f"{provider}:{model}"`.
    """

    entries: dict[str, ProviderUsage] = field(default_factory=dict)


def _today() -> str:
    return datetime.now(tz=UTC).date().isoformat()


def load() -> QuotaState:
    path = _quota_path()
    if not path.exists():
        return QuotaState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = {
        key: ProviderUsage(**val) for key, val in raw.get("entries", {}).items()
    }
    return QuotaState(entries=entries)


def save(state: QuotaState) -> None:
    path = _quota_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entries": {key: asdict(val) for key, val in state.entries.items()},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def key_of(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def get(state: QuotaState, provider: str, model: str) -> ProviderUsage:
    key = key_of(provider, model)
    if key not in state.entries:
        state.entries[key] = ProviderUsage(date=_today())
    return state.entries[key]


def record_success(
    state: QuotaState,
    *,
    provider: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> None:
    usage = get(state, provider, model)
    today = _today()
    if usage.date != today:
        usage.date = today
        usage.requests_used = 0
        usage.tokens_used = 0
    usage.requests_used += 1
    usage.tokens_used += tokens_in + tokens_out
    usage.consecutive_failures = 0
    usage.last_success_at = datetime.now(tz=UTC).isoformat()


def record_failure(
    state: QuotaState,
    *,
    provider: str,
    model: str,
    reason: str,
    auto_disable_after: int = 3,
) -> None:
    usage = get(state, provider, model)
    today = _today()
    if usage.date != today:
        usage.date = today
        usage.requests_used = 0
        usage.tokens_used = 0
    usage.requests_used += 1
    usage.consecutive_failures += 1
    usage.last_failure_reason = reason
    if usage.consecutive_failures >= auto_disable_after:
        # Disable for 24 h; weekly smoke-test will re-enable on first success.
        usage.disabled_until = today


def is_disabled(usage: ProviderUsage) -> bool:
    if usage.disabled_until is None:
        return False
    return usage.disabled_until >= _today()


def remaining_hint(usage: ProviderUsage) -> str:
    """Short human-readable string for plan/CLI output."""
    if is_disabled(usage):
        return f"disabled until {usage.disabled_until}"
    return f"{usage.requests_used} req used today"
