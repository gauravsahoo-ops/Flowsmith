"""Periodic reconciliation of connector packs across API/worker processes.

Install/upgrade/uninstall operations update PostgreSQL. Each API and worker
process runs this reconciler so a pack change made by one replica reaches the
others without a restart. Uninstall tombstones remain in the database so a
worker that was offline during removal still drops the connector when it
returns.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import ConnectorPack, ConnectorPackTombstone
from app.services.connector_pack_runtime import generated_dir, materialize_pack

logger = logging.getLogger("connector_packs.reconciler")

RECONCILE_INTERVAL_SECONDS = 10.0
_KNOWN: dict[str, str] = {}
_LOCK = threading.Lock()


def _required_sources(key: str) -> list[str]:
    return [f"gen_{key}_{suffix}.py" for suffix in ("provider", "definition", "connector")]


def _source_digest(pack: ConnectorPack) -> str:
    if pack.manifest_sha256:
        return pack.manifest_sha256
    encoded = json.dumps(pack.generated_sources or {}, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _remove_files(key: str) -> None:
    for filename in _required_sources(key):
        try:
            (generated_dir() / filename).unlink(missing_ok=True)
        except OSError:
            logger.exception("could not remove generated pack file %s", filename)


def _unload(key: str) -> None:
    try:
        from app.connectors import get_registry

        get_registry().unregister(key)
    except Exception:
        logger.exception("could not unregister pack %s", key)
    try:
        from app.connectors.openapi_emit import invalidate_generated_modules

        invalidate_generated_modules(key)
    except Exception:
        logger.exception("could not invalidate generated modules for %s", key)
    _remove_files(key)
    _KNOWN.pop(key, None)


def reconcile_packs(*, force: bool = False) -> dict[str, int]:
    """Bring this process's generated modules in line with PostgreSQL."""
    from app.connectors import get_registry
    from app.connectors.openapi_emit import (
        invalidate_generated_modules,
        register_generated,
    )

    with _LOCK:
        db = get_session()
        try:
            packs = db.execute(select(ConnectorPack)).scalars().all()
            tombstones = set(
                db.execute(select(ConnectorPackTombstone.connector_key)).scalars().all()
            )
        finally:
            db.close()

        registry = get_registry()
        unregistered = 0

        for key in tombstones:
            if key in _KNOWN or registry.get_definition(key) is not None:
                _unload(key)
                unregistered += 1
            else:
                _remove_files(key)

        installed = {pack.connector_key: pack for pack in packs}
        for key in list(_KNOWN):
            if key not in installed and key not in tombstones:
                _unload(key)
                unregistered += 1

        raw_revoked = get_settings().connector_pack_revoked_keys or ""
        revoked_keys = {part.strip() for part in raw_revoked.split(",") if part.strip()}
        revoked_packs = {
            key
            for key, pack in installed.items()
            if pack.signing_key_id and pack.signing_key_id in revoked_keys
        }
        for key in revoked_packs:
            if key in _KNOWN or registry.get_definition(key) is not None:
                _unload(key)
                unregistered += 1

        changed: list[str] = []
        for key, pack in installed.items():
            if key in tombstones or key in revoked_packs:
                continue
            digest = _source_digest(pack)
            if (
                not force
                and _KNOWN.get(key) == digest
                and registry.get_definition(key) is not None
            ):
                continue
            if not materialize_pack(pack):
                continue
            # register_generated(allow_idempotent=True) keeps the previous
            # definition when the generated version string is unchanged, so
            # explicitly drop the old entry before loading upgraded sources.
            registry.unregister(key)
            invalidate_generated_modules(key)
            _KNOWN[key] = digest
            changed.append(key)

        if changed:
            register_generated(registry, str(generated_dir()))

        return {"registered": len(changed), "unregistered": unregistered}


class PackReconciler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(reconcile_packs)
            except Exception:
                logger.exception("connector-pack reconciliation failed")
            await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


pack_reconciler = PackReconciler()
