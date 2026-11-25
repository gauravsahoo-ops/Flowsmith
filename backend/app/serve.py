"""Public deployment entry point (M9): `python -m app.serve`.

Serves the whole product on a single port — built UI, API, webhooks and
the live stream — so a tunnel or reverse proxy can publish one URL.
Phase 7: structured JSON logging is enabled here by default
(`LOG_FORMAT=json`, `LOG_LEVEL` to control verbosity).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import uvicorn

from app.config import Settings, get_settings
from app.logging_setup import setup_logging

logger = logging.getLogger("app.serve")


def _resolve_workers(settings: Settings) -> int:
    """Resolve Uvicorn worker count safely from WEB_CONCURRENCY.

    Multi-worker mode is only safe in production when embedded queue execution
    is disabled (`QUEUE_EMBEDDED_CONSUMER=false`) and `reload` is off.
    """
    raw = os.environ.get("WEB_CONCURRENCY", "").strip()
    if not raw:
        return 1
    try:
        requested = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid WEB_CONCURRENCY=%r; using 1 worker", raw)
        return 1
    if requested < 1:
        logger.warning("Ignoring WEB_CONCURRENCY=%d (< 1); using 1 worker", requested)
        return 1
    if requested > 1 and settings.app_env == "development":
        logger.warning(
            "Ignoring WEB_CONCURRENCY=%d in development reload mode; using 1 worker",
            requested,
        )
        return 1
    if requested > 1 and settings.queue_embedded_consumer:
        logger.warning(
            "Ignoring WEB_CONCURRENCY=%d while QUEUE_EMBEDDED_CONSUMER=true; "
            "set QUEUE_EMBEDDED_CONSUMER=false with external workers before scaling API processes; "
            "using 1 worker",
            requested,
        )
        return 1
    return requested


def _resolve_forwarded_allow_ips(settings: Settings) -> str:
    """Align Uvicorn ProxyHeadersMiddleware trust list with TRUSTED_PROXIES."""
    override = os.environ.get("FORWARDED_ALLOW_IPS", "").strip()
    if override:
        return override
    return settings.trusted_proxies or "127.0.0.1,::1"


def build_uvicorn_kwargs(settings: Settings | None = None) -> dict[str, Any]:
    """Build keyword arguments passed to `uvicorn.run`."""
    resolved = settings or get_settings()
    is_dev = resolved.app_env == "development"
    workers = _resolve_workers(resolved)
    uvicorn_kwargs: dict[str, Any] = {
        "host": resolved.host,
        "port": resolved.port,
        "reload": is_dev,
        "log_config": None,  # our root handler owns logging; uvicorn logs propagate
        "access_log": False,
        "proxy_headers": True,
        "forwarded_allow_ips": _resolve_forwarded_allow_ips(resolved),
    }
    if workers > 1:
        uvicorn_kwargs["workers"] = workers
    if is_dev:
        uvicorn_kwargs["reload_dirs"] = ["app"]
        uvicorn_kwargs["reload_includes"] = ["*.py"]
        uvicorn_kwargs["reload_excludes"] = [
            "*.log",
            "*.db",
            "*.sqlite*",
            "data",
            "data/*",
            "tmp",
            "tmp/*",
            "worker_alive",
            ".pytest_cache",
            "__pycache__",
        ]
    return uvicorn_kwargs


def main() -> None:
    setup_logging()
    uvicorn.run("app.main:app", **build_uvicorn_kwargs())


if __name__ == "__main__":
    main()
