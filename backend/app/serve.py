"""Public deployment entry point (M9): `python -m app.serve`.

Serves the whole product on a single port — built UI, API, webhooks and
the live stream — so a tunnel or reverse proxy can publish one URL.
Phase 7: structured JSON logging is enabled here by default
(`LOG_FORMAT=json`, `LOG_LEVEL` to control verbosity).
"""

from __future__ import annotations

from typing import Any

import uvicorn

from app.config import get_settings
from app.logging_setup import setup_logging


def main() -> None:
    setup_logging()
    settings = get_settings()
    is_dev = settings.app_env == "development"
    uvicorn_kwargs: dict[str, Any] = {
        "host": settings.host,
        "port": settings.port,
        "reload": is_dev,
        "log_config": None,  # our root handler owns logging; uvicorn logs propagate
        "access_log": False,
    }
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

    uvicorn.run("app.main:app", **uvicorn_kwargs)


if __name__ == "__main__":
    main()
