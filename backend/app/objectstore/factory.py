"""Factory for the configured object store backend (Phase 19)."""

from __future__ import annotations

import threading
from typing import Any

from app.config import get_settings

_lock = threading.Lock()
_instance: Any | None = None
_checked_backend: str = ""


def get_object_store():
    """Singleton for the configured backend (local by default)."""
    global _instance, _checked_backend
    backend = (get_settings().object_store_backend or "local").lower()
    with _lock:
        if _instance is not None and _checked_backend == backend:
            return _instance
        if backend == "local":
            from app.objectstore.local import LocalObjectStore
            _instance = LocalObjectStore()
        elif backend == "s3":
            from app.objectstore.s3 import S3ObjectStore
            _instance = S3ObjectStore()
        else:
            raise ValueError(f"Unknown object store backend '{backend}' (expected local|s3)")
        _checked_backend = backend
        return _instance


def reset_object_store() -> None:  # test helper
    global _instance, _checked_backend
    with _lock:
        _instance = None
        _checked_backend = ""
