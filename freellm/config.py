"""User configuration layer for freellm.

Three layers, in precedence order (last wins):

1. **Built-in catalog** (`freellm/providers.py`) — curated default
   shipped with the library. 28+ entries across 7 modalities.

2. **YAML config file** — drop a `freellm.yaml` in the project root,
   OR set `FREELLM_CONFIG_PATH=/path/to/freellm.yaml`. Reads at
   process start. Lets ops:
   - Add new providers without forking the library.
   - Disable specific providers (e.g. `disable: [replicate]`).
   - Re-order priority per modality.
   - Override per-provider env-var names.
   - Override the per-modality `default_chain` priority list.

3. **Programmatic API** — call `freellm.configure(...)` once at
   startup. Wins over both. Useful in tests + when consumers want
   declarative config in Python without a YAML file.

Example `freellm.yaml`:

```yaml
disable:
  - replicate              # we hit Replicate's free quota; skip
order:
  text:
    - cerebras             # try Cerebras first; faster than Groq for our prompts
    - groq
    - gemini
extra_providers:
  text:
    - provider: my_proxy
      model: my-llama-70b
      env_var: MY_PROXY_KEY
      speed_tier: fast
      last_verified: "2026-04-26"
      free_tier:
        kind: rpm_rpd
        rpm: 60
        rpd: 100000
```

Equivalent programmatic call:

```python
import freellm
from datetime import date

freellm.configure(
    disable=["replicate"],
    order={"text": ["cerebras", "groq", "gemini"]},
    extra_providers={
        "text": [{
            "provider": "my_proxy",
            "model": "my-llama-70b",
            "env_var": "MY_PROXY_KEY",
            "speed_tier": "fast",
            "last_verified": date(2026, 4, 26),
            "free_tier": {"kind": "rpm_rpd", "rpm": 60, "rpd": 100000},
        }],
    },
)
```
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from freellm.providers import PROVIDERS as BUILTIN_PROVIDERS
from freellm.schemas import ALL_MODALITIES, Modality, ProviderEntry

# ============================================================
# Public state — `effective` is what router.py reads.
# ============================================================


@dataclass
class FreellmConfig:
    """Resolved config after layering env file + programmatic call on top of
    the built-in catalog. Read-only by convention; mutate via `configure()`.
    """

    providers: dict[Modality, list[ProviderEntry]] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)
    """Set of `provider` slugs to drop entirely (e.g. {"replicate"})."""

    order: dict[Modality, list[str]] = field(default_factory=dict)
    """Per-modality preferred provider order; partial — unspecified providers
    keep their built-in order, listed providers are surfaced first."""

    @property
    def total_entries(self) -> int:
        return sum(len(v) for v in self.providers.values())


_state: FreellmConfig = FreellmConfig(providers=deepcopy(BUILTIN_PROVIDERS))


def get_config() -> FreellmConfig:
    """Return the live, layered config. Router uses this."""
    return _state


def reset() -> None:
    """Restore built-in catalog as the only layer. Useful in tests."""
    global _state
    _state = FreellmConfig(providers=deepcopy(BUILTIN_PROVIDERS))


# ============================================================
# Programmatic API
# ============================================================


def configure(
    *,
    disable: Iterable[str] | None = None,
    order: dict[Modality, list[str]] | None = None,
    extra_providers: dict[Modality, list[dict[str, Any]]] | None = None,
    reset_first: bool = False,
) -> FreellmConfig:
    """Apply user overrides on top of the current state.

    - `disable`: provider slugs to remove from every modality.
    - `order`: per-modality preferred provider sequence (partial). Listed
      provider slugs surface first in the chain; unlisted entries keep
      their built-in relative order, appended at the end.
    - `extra_providers`: extra rows per modality. Each dict is fed to
      `ProviderEntry.model_validate()` so the same shape as
      `freellm.yaml` is accepted. Free-tier kind = discriminator value.
    - `reset_first`: if True, drop everything (file + previous configure)
      and start from the built-in catalog before applying these args.

    Returns the resulting `FreellmConfig`.
    """
    global _state
    if reset_first:
        reset()

    cfg = _state

    if extra_providers:
        for modality, rows in extra_providers.items():
            if modality not in ALL_MODALITIES:
                raise ValueError(f"unknown modality {modality!r}")
            existing = list(cfg.providers.get(modality, []))
            for row in rows:
                entry = ProviderEntry.model_validate(row)
                # Replace if (provider, model) already present.
                key = (entry.provider, entry.model)
                existing = [
                    e for e in existing if (e.provider, e.model) != key
                ] + [entry]
            cfg.providers[modality] = existing

    if disable:
        cfg.disabled |= set(disable)
        for modality, entries in list(cfg.providers.items()):
            cfg.providers[modality] = [
                e for e in entries if e.provider not in cfg.disabled
            ]

    if order:
        for modality, prefs in order.items():
            if modality not in ALL_MODALITIES:
                raise ValueError(f"unknown modality {modality!r}")
            cfg.order[modality] = list(prefs)
            cfg.providers[modality] = _reorder(cfg.providers.get(modality, []), prefs)

    return cfg


def _reorder(
    entries: list[ProviderEntry], preferred: list[str]
) -> list[ProviderEntry]:
    """Return entries in the user's preferred provider order. Stable for
    entries with the same provider; unlisted providers keep their relative
    order at the tail.
    """
    pref_index = {p: i for i, p in enumerate(preferred)}
    front: list[ProviderEntry] = []
    tail: list[ProviderEntry] = []
    for e in entries:
        if e.provider in pref_index:
            front.append(e)
        else:
            tail.append(e)
    front.sort(key=lambda e: pref_index[e.provider])
    return front + tail


# ============================================================
# YAML config-file loader
# ============================================================


def _config_path() -> Path | None:
    explicit = os.environ.get("FREELLM_CONFIG_PATH", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    candidates = [
        Path.cwd() / "freellm.yaml",
        Path.cwd() / "freellm.yml",
        Path.cwd() / ".freellm.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_from_yaml(path: str | Path | None = None) -> FreellmConfig:
    """Load `freellm.yaml` if present, layer on top of current state.

    Returns the new `FreellmConfig`. Idempotent — calling twice on the
    same file is equivalent to one call (uses replace-by-(provider, model)).

    `path=None` → search PWD for freellm.yaml / freellm.yml / .freellm.yaml
    in that order. If `FREELLM_CONFIG_PATH` is set in the env, it takes
    precedence over the PWD search.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as e:
        raise ImportError(
            "Install the `yaml` extra: `pip install 'freellm[yaml]'`"
        ) from e

    if path is None:
        resolved = _config_path()
        if resolved is None:
            return _state
    else:
        resolved = Path(path).expanduser()
        if not resolved.exists():
            raise FileNotFoundError(resolved)

    with resolved.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"{resolved}: top-level must be a mapping")

    return configure(
        disable=raw.get("disable") or None,
        order=raw.get("order") or None,
        extra_providers=raw.get("extra_providers") or None,
    )


# Auto-load YAML config at import time IF a freellm.yaml exists in PWD or
# FREELLM_CONFIG_PATH is set. Opt-out: FREELLM_NO_AUTO_LOAD=1 (useful in
# tests, or when the calling app wants strict reset semantics).
def _maybe_auto_load() -> None:
    if os.environ.get("FREELLM_NO_AUTO_LOAD") == "1":
        return
    if _config_path() is None:
        return
    try:
        load_from_yaml()
    except ImportError:
        # PyYAML not installed and no config file is being used today;
        # silently skip rather than fail import for users who don't
        # need YAML.
        pass


_maybe_auto_load()
