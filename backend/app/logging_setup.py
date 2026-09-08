"""Structured logging setup (Phase 7).

`setup_logging()` configures Python logging to emit one JSON object per
line (timestamp, level, logger, message + extra fields) when
`LOG_FORMAT=json` (default in production entrypoints), else the normal
human format. `LOG_LEVEL` controls verbosity.

Sensitive values are never logged by the request middleware: only
method, path, status, duration and (when authenticated) the user id.
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
from datetime import UTC, datetime
from typing import Any

try:
    import uvicorn
except Exception:  # pragma: no cover - uvicorn is always installed
    uvicorn = None  # type: ignore[assignment]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _log_level() -> str:
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def setup_logging() -> None:
    fmt = os.environ.get("LOG_FORMAT", "json").lower()
    if fmt == "json":
        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(_log_level())
    # uvicorn loggers inherit the root handler (its default config is not
    # applied when we never pass log_config to uvicorn.run).
    if uvicorn is not None:
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            lg = logging.getLogger(name)
            lg.handlers[:] = []
            lg.propagate = True
