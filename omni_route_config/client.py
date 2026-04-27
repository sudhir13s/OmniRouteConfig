"""OpenAI-SDK adapter pointed at a local OmniRoute proxy.

OmniRoute exposes OpenAI-compatible routes at `<base>/api/v1/*`
(chat/completions, embeddings, completions, models, ...). Any client
that speaks OpenAI's HTTP shape works against it — just override
`base_url`. This module wraps that override so callers don't have
to remember the path.

Importing this module requires the optional `client` extra:

    pip install "omni-route-config[client]"
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import OpenAI


def _omniroute_base() -> str:
    base = os.environ.get("OMNIROUTE_URL", "http://localhost:20128").rstrip("/")
    return f"{base}/api/v1"


def openai_for_omniroute(
    *,
    api_key: str | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> OpenAI:
    """Return a configured `openai.OpenAI` pointed at the local OmniRoute.

    `api_key` is whatever value OmniRoute itself wants for `Authorization:
    Bearer ...`. If OmniRoute has `REQUIRE_API_KEY=true` in its env, you
    must pass the key you registered with OmniRoute; otherwise any
    placeholder works.

    Defaults `api_key=os.environ.get("OMNIROUTE_API_TOKEN", "sk-omniroute-local")`.

    Extra kwargs are forwarded to the OpenAI constructor (e.g. `timeout`,
    `max_retries`, `default_headers`).
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError(
            "Install the `client` extra: `pip install 'omni-route-config[client]'`"
        ) from e

    key = (
        api_key
        or os.environ.get("OMNIROUTE_API_TOKEN", "").strip()
        or "sk-omniroute-local"
    )
    return OpenAI(
        base_url=_omniroute_base(),
        api_key=key,
        **(extra_kwargs or {}),
    )
