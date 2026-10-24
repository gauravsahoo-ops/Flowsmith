"""Materialize installed connector packs in API and worker processes.

The pack installer stores the generated provider/definition/connector source
in PostgreSQL as well as writing it to the installing process's generated
directory. Other API replicas and queue workers can therefore recreate the
same connector files on startup or lazily when they encounter an unknown
connector node type. This does not depend on a shared container filesystem.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

from sqlalchemy import select

from app.db import get_session
from app.models import ConnectorPack

logger = logging.getLogger("connector_packs.runtime")

_MATERIALIZE_LOCK = threading.Lock()
_LAST_ATTEMPT: dict[str, float] = {}
_ATTEMPT_COOLDOWN_SECONDS = 5.0
_SAFE_KEY = re.compile(r"^[a-z0-9_]+$")


def generated_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "connectors" / "generated"


def clear_pack_cache(connector_key: str | None = None) -> None:
    if connector_key is None:
        _LAST_ATTEMPT.clear()
    else:
        _LAST_ATTEMPT.pop(connector_key, None)


def materialize_pack(pack: ConnectorPack) -> bool:
    return _materialize_sources(pack)


def _materialize_sources(pack: ConnectorPack) -> bool:
    key = pack.connector_key
    if not _SAFE_KEY.fullmatch(key):
        logger.warning("connector pack %r has an unsafe connector key", key)
        return False
    sources = pack.generated_sources or {}
    if not isinstance(sources, dict):
        logger.warning("connector pack %s has invalid generated sources", key)
        return False
    filenames = [f"gen_{key}_{suffix}.py" for suffix in ("provider", "definition", "connector")]
    if any(not isinstance(sources.get(name), str) for name in filenames):
        logger.warning("connector pack %s is missing one or more generated sources", key)
        return False

    directory = generated_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with _MATERIALIZE_LOCK:
            for filename in filenames:
                (directory / filename).write_text(sources[filename], encoding="utf-8")
    except OSError:
        logger.exception("could not materialize connector pack %s", key)
        return False
    return True


def load_installed_packs() -> int:
    """Reconcile installed packs and tombstones; return registered count."""
    from app.services.connector_pack_reconciler import reconcile_packs

    try:
        return reconcile_packs(force=True).get("registered", 0)
    except Exception:
        logger.exception("could not load installed connector packs")
        return 0


def ensure_pack_connector(connector_key: str) -> bool:
    """Lazily load a pack installed after this process started.

    Returns True when the connector is registered. Negative attempts are
    briefly cached so unknown/typo node types do not hammer PostgreSQL.
    """
    from app.connectors import get_registry
    from app.connectors.openapi_emit import register_generated

    registry = get_registry()
    if registry.get_definition(connector_key) is not None:
        return True
    if not _SAFE_KEY.fullmatch(connector_key):
        return False

    now = time.monotonic()
    if now - _LAST_ATTEMPT.get(connector_key, 0.0) < _ATTEMPT_COOLDOWN_SECONDS:
        return False
    _LAST_ATTEMPT[connector_key] = now

    db = get_session()
    try:
        pack = db.scalar(
            select(ConnectorPack).where(ConnectorPack.connector_key == connector_key)
        )
        if pack is None or not _materialize_sources(pack):
            return False
    except Exception:
        logger.exception("could not load connector pack %s", connector_key)
        return False
    finally:
        db.close()

    try:
        register_generated(registry, str(generated_dir()))
    except Exception:
        logger.exception("could not register connector pack %s", connector_key)
        return False
    return registry.get_definition(connector_key) is not None
