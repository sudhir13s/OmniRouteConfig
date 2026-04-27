"""Bootstrap helpers — install + start OmniRoute, push catalog, tear down.

Three paths, in order of preference:

1. Already running on `OMNIROUTE_URL` (default http://localhost:20128)
   -> we just confirm it's reachable and apply config.

2. `npx omniroute@latest` available on PATH
   -> spawn it as a background process; PID stashed in `.omniroute/pid`.

3. Docker available
   -> spawn the published image (`diegosouzapw/omniroute:latest`).

Every path returns the same `OmniRouteStatus`. Callers don't care which.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from omni_route_config.catalog import (
    ProviderCatalog,
    ProviderEntry,
    env_var_present,
    filter_runnable,
    load_catalog,
)
from omni_route_config.types import (
    ApplyResult,
    OmniRouteStatus,
    ProviderApply,
)

DEFAULT_PORT = 20128
DEFAULT_URL = "http://localhost:20128"
PID_DIR = Path(".omniroute")

# Docker run defaults — overridable via env so users can point at their own
# fork build (e.g. `omniroute:full` from `docker compose --profile full build`).
DEFAULT_CONTAINER = "omniroute"
DEFAULT_IMAGE = "diegosouzapw/omniroute:latest"
DEFAULT_VOLUME = "omniroute-data"


def _docker_container_name() -> str:
    return os.environ.get("OMNIROUTE_CONTAINER", DEFAULT_CONTAINER)


def _docker_image() -> str:
    return os.environ.get("OMNIROUTE_IMAGE", DEFAULT_IMAGE)


def _docker_volume() -> str:
    return os.environ.get("OMNIROUTE_VOLUME", DEFAULT_VOLUME)

# `/api/init` returns `{"initialized": true|false}` and is the canonical
# health endpoint in OmniRoute (verified against v3.7.x). `/api/health`
# and `/api/version` do NOT exist upstream. `/` returns a 307 redirect
# to the dashboard — kept as a final fallback so we still detect a live
# server even if `/api/init` is renamed in a future version.
_HEALTH_PATHS = ("/api/init", "/")


def _base_url() -> str:
    return os.environ.get("OMNIROUTE_URL", DEFAULT_URL).rstrip("/")


def _bearer_headers() -> dict[str, str]:
    token = os.environ.get("OMNIROUTE_API_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


# ============================================================
# health probes
# ============================================================


async def _is_reachable(base: str, *, timeout: float = 2.0) -> tuple[bool, str | None]:
    """Ping a couple of likely health endpoints. Return (reachable, version_or_none)."""
    async with httpx.AsyncClient(timeout=timeout, headers=_bearer_headers()) as c:
        for path in _HEALTH_PATHS:
            try:
                resp = await c.get(f"{base}{path}")
            except httpx.HTTPError:
                continue
            if resp.status_code < 500:
                version = None
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        body = resp.json()
                        if isinstance(body, dict):
                            # Different endpoints surface different fields:
                            # /api/init -> {"initialized": true}
                            # /api/version (legacy) -> {"version": "..."}
                            version = body.get("version") or body.get("instance", {}).get("version")
                    except ValueError:
                        pass
                return True, version
    return False, None


async def status() -> OmniRouteStatus:
    """Return current OmniRouteStatus snapshot. Never raises — wraps errors as `detail`."""
    base = _base_url()
    reachable, version = await _is_reachable(base)
    providers_configured = 0
    detail = None
    if reachable:
        try:
            async with httpx.AsyncClient(timeout=5.0, headers=_bearer_headers()) as c:
                r = await c.get(f"{base}/api/providers")
            if r.status_code == 200:
                payload: Any = r.json()
                providers_configured = len(payload.get("connections") or [])
        except httpx.HTTPError as e:
            detail = f"providers list error: {e}"
    return OmniRouteStatus(
        base_url=base,
        reachable=reachable,
        version=version,
        providers_configured=providers_configured,
        detail=detail,
    )


# ============================================================
# launchers
# ============================================================


def _can_use_npx() -> bool:
    return shutil.which("npx") is not None


def _can_use_docker() -> bool:
    return shutil.which("docker") is not None


def _spawn(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.Popen:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    log = (PID_DIR / "omniroute.log").open("a", buffering=1, encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        stdout=log,
        stderr=subprocess.STDOUT,
        env={**os.environ, **(env or {})},
        start_new_session=True,
    )
    (PID_DIR / "pid").write_text(str(proc.pid), encoding="utf-8")
    return proc


async def _wait_until_reachable(base: str, *, timeout_s: int = 60) -> bool:
    """Poll until reachable or timeout. Returns True if reachable."""
    for _ in range(timeout_s):
        ok, _ = await _is_reachable(base, timeout=1.5)
        if ok:
            return True
        await asyncio.sleep(1)
    return False


async def ensure_running(
    *,
    port: int | None = None,
    timeout_s: int = 90,
    prefer: Iterable[str] = ("existing", "npx", "docker"),
) -> OmniRouteStatus:
    """Idempotent: returns OmniRouteStatus once OmniRoute is reachable.

    Tries strategies in `prefer` order. Default is to detect an
    existing instance first (so a CI environment that pre-starts
    OmniRoute via Docker just sees `existing` and proceeds).

    `port`: if provided, sets OMNIROUTE_URL to http://localhost:<port>
    BEFORE the existence check (so callers can customize without env).

    `timeout_s`: total ceiling spent polling.
    """
    if port is not None:
        os.environ["OMNIROUTE_URL"] = f"http://localhost:{port}"
    base = _base_url()

    for strategy in prefer:
        if strategy == "existing":
            ok, _ = await _is_reachable(base)
            if ok:
                return await status()
        elif strategy == "npx":
            if not _can_use_npx():
                continue
            _spawn(
                ["npx", "-y", "omniroute@latest", "--no-open", "--port", str(port or DEFAULT_PORT)],
            )
        elif strategy == "docker":
            if not _can_use_docker():
                continue
            _start_docker(port=port or DEFAULT_PORT)
        if await _wait_until_reachable(base, timeout_s=timeout_s):
            return await status()

    return OmniRouteStatus(
        base_url=base,
        reachable=False,
        detail="Failed to reach OmniRoute via any strategy in `prefer`.",
    )


def _docker_inspect_state(name: str) -> str | None:
    """Returns the docker State.Status of a container or None if missing.

    States: "created", "running", "paused", "restarting", "removing",
    "exited", "dead". None means the container does not exist.
    """
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _start_docker(*, port: int) -> None:
    """Run OmniRoute in Docker with --env-file + persistent named volume.

    Idempotent: if a container with the configured name is already
    running, this is a no-op. If it exists but is stopped, we `docker
    start` instead of re-running.
    """
    name = _docker_container_name()
    state = _docker_inspect_state(name)
    if state == "running":
        return
    if state in ("exited", "created", "dead"):
        subprocess.run(["docker", "start", name], check=False, capture_output=True)
        return

    cmd: list[str] = [
        "docker", "run", "-d",
        "--name", name,
        "--restart", "unless-stopped",
        "-p", f"{port}:20128",
        "-v", f"{_docker_volume()}:/app/data",
    ]
    env_file = Path(os.environ.get("OMNIROUTE_ENV_FILE", ".env"))
    if env_file.exists():
        cmd += ["--env-file", str(env_file.resolve())]
    cmd.append(_docker_image())
    PID_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    log_path = PID_DIR / "omniroute.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"$ {' '.join(cmd)}\n")
        if proc.stdout:
            f.write(proc.stdout)
        if proc.stderr:
            f.write(proc.stderr)
    if proc.returncode != 0:
        # Surface to caller so `up`/`init` doesn't silently report
        # "reachable" when docker run actually failed.
        raise RuntimeError(
            f"docker run failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip() or 'no output'}"
        )


def _stop_docker() -> bool:
    """Stop the docker container if running. True if a stop happened."""
    name = _docker_container_name()
    state = _docker_inspect_state(name)
    if state is None:
        return False
    if state != "running":
        # Container exists but isn't running — remove the stale entry.
        subprocess.run(["docker", "rm", name], check=False, capture_output=True)
        return False
    subprocess.run(["docker", "stop", name], check=False, capture_output=True)
    subprocess.run(["docker", "rm", name], check=False, capture_output=True)
    return True


def tear_down() -> bool:
    """Stop the OmniRoute instance this CLI started. Idempotent.

    Tries the docker container first (named, restart-policy aware); falls
    back to PID-file based npx process. Returns True if anything was stopped.
    """
    stopped_docker = _stop_docker()

    pid_file = PID_DIR / "pid"
    stopped_proc = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, 15)  # SIGTERM
            stopped_proc = True
        except (OSError, ValueError, ProcessLookupError):
            pass
        pid_file.unlink(missing_ok=True)

    return stopped_docker or stopped_proc


def destroy_volume() -> bool:
    """Remove the persistent docker volume. DESTROYS all OmniRoute data
    (admin accounts, provider connections, logs). Caller must confirm.
    Returns True if a volume was removed.
    """
    if not _can_use_docker():
        return False
    vol = _docker_volume()
    proc = subprocess.run(
        ["docker", "volume", "rm", vol], capture_output=True, text=True, check=False
    )
    return proc.returncode == 0


# ============================================================
# config push
# ============================================================


async def _post_provider(
    client: httpx.AsyncClient,
    base: str,
    entry: ProviderEntry,
) -> ProviderApply:
    api_key = os.environ.get(entry.env_var, "").strip()
    payload: dict[str, Any] = {
        "provider": entry.provider,
        "apiKey": api_key,
        "name": entry.name or entry.provider,
        "priority": entry.priority,
    }
    if entry.default_model:
        payload["defaultModel"] = entry.default_model
    if entry.provider_specific_data:
        payload["providerSpecificData"] = entry.provider_specific_data
    try:
        resp = await client.post(f"{base}/api/providers", json=payload)
    except httpx.HTTPError as e:
        return ProviderApply(
            provider=entry.provider,
            env_var=entry.env_var,
            status="error",
            detail=str(e),
        )
    if resp.status_code in (200, 201):
        body = resp.json() if "json" in resp.headers.get("content-type", "") else {}
        return ProviderApply(
            provider=entry.provider,
            env_var=entry.env_var,
            status="applied",
            omniroute_id=(body.get("connection") or body).get("id"),
        )
    if resp.status_code == 409 or "already" in resp.text.lower():
        return ProviderApply(
            provider=entry.provider,
            env_var=entry.env_var,
            status="already_present",
        )
    return ProviderApply(
        provider=entry.provider,
        env_var=entry.env_var,
        status="error",
        detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
    )


async def apply_config(
    catalog: ProviderCatalog | None = None,
    *,
    base_url: str | None = None,
) -> ApplyResult:
    """POST every runnable catalog entry to OmniRoute /api/providers.

    Idempotent — already-configured providers are reported as
    `already_present`, not re-POSTed.

    `catalog=None` reads `config/free-providers.yaml` (or the
    OMNI_ROUTE_CONFIG_PATH env var). Pass an explicit ProviderCatalog
    to skip the file load.
    """
    if catalog is None:
        catalog = load_catalog()
    base = (base_url or _base_url()).rstrip("/")

    items: list[ProviderApply] = []
    skipped = 0
    for entry in catalog.providers:
        if not entry.enabled:
            continue
        if not env_var_present(entry):
            skipped += 1
            items.append(
                ProviderApply(
                    provider=entry.provider,
                    env_var=entry.env_var,
                    status="skipped_missing_key",
                )
            )

    runnable = filter_runnable(catalog)
    async with httpx.AsyncClient(timeout=15.0, headers=_bearer_headers()) as client:
        for entry in runnable:
            items.append(await _post_provider(client, base, entry))

    return ApplyResult(
        total=len(catalog.providers),
        applied=sum(1 for i in items if i.status == "applied"),
        already_present=sum(1 for i in items if i.status == "already_present"),
        skipped_missing_key=sum(1 for i in items if i.status == "skipped_missing_key"),
        errors=sum(1 for i in items if i.status == "error"),
        items=items,
    )
