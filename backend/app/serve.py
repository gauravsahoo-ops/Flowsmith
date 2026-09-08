"""Public deployment entry point (M9): `python -m app.serve`.

Serves the whole product on a single port — built UI, API, webhooks and
the live stream — so a tunnel or reverse proxy can publish one URL.
Phase 7: structured JSON logging is enabled here by default
(`LOG_FORMAT=json`, `LOG_LEVEL` to control verbosity).
"""

from __future__ import annotations

import uvicorn

from app.config import get_settings
from app.logging_setup import setup_logging


def main() -> None:
    setup_logging()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,  # our root handler owns logging; uvicorn logs propagate
    )


if __name__ == "__main__":
    main()
