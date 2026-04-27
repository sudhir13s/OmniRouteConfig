"""OmniRouteConfig — configure + bootstrap OmniRoute for $0-spend AI routing.

Public API:

    from omni_route_config import (
        bootstrap,        # ensure_running, apply_config, tear_down
        client,           # openai_for_omniroute()
        load_catalog,     # parse the bundled free-providers.yaml
        ProviderEntry,    # catalog row schema
        ApplyResult,      # what apply_config() returns
    )

OmniRoute itself ships separately. This package writes config TO it
via REST + provides Python ergonomics (OpenAI SDK pre-pointed at
the local proxy, idempotent setup helpers, typed catalog).

See README for installation + usage.
"""

from __future__ import annotations

from omni_route_config import bootstrap, client, registry
from omni_route_config.catalog import (
    ProviderCatalog,
    ProviderEntry,
    load_catalog,
)
from omni_route_config.types import (
    ApplyResult,
    ModelEntry,
    ModelType,
    OmniRouteStatus,
    ProviderRegistry,
    SyncDiff,
)

__version__ = "0.2.0"

__all__ = [
    "ApplyResult",
    "ModelEntry",
    "ModelType",
    "OmniRouteStatus",
    "ProviderCatalog",
    "ProviderEntry",
    "ProviderRegistry",
    "SyncDiff",
    "__version__",
    "bootstrap",
    "client",
    "load_catalog",
    "registry",
]
