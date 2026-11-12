"""Live HubSpot object discovery API.

The HubSpot node's object picker must include custom objects created after
the OAuth connection was made. HubSpot exposes those through
``GET /crm/v3/schemas``; this router resolves the caller's HubSpot
credential, runs the connector's ``list_object_types`` operation and caches
the result briefly (portal schema changes are rare).

    GET /api/connectors/hubspot/objects

The caller's most recent ``hubspot`` credential is used unless an explicit
``credential_id`` query parameter is supplied. When the private app / OAuth
grant lacks schema read access, standard objects are still returned with a
``custom_error`` message instead of failing the picker.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.connectors import ConnectorError, get_registry as get_connector_registry
from app.credentials.service import CredentialError, resolve_credentials
from app.db import get_db
from app.models import Credential, User

router = APIRouter(prefix="/api/connectors/hubspot", tags=["connectors"])
logger = logging.getLogger("hubspot.discovery")

HUBSPOT_DISCOVERY_TTL_S = 300.0

# {key: (expires_at_monotonic, payload)}; single event loop -> dict ops are safe.
_discovery_cache: dict[tuple[str, int, str], tuple[float, Any]] = {}


def _discovery_key(user_id: int, credential_id: str) -> tuple[str, int, str]:
    return ("hs-discovery", user_id, credential_id)


def clear_discovery_cache() -> None:
    """Test hook / manual invalidation."""
    _discovery_cache.clear()


def _cached(key: tuple[str, int, str]) -> Any | None:
    hit = _discovery_cache.get(key)
    if hit is None:
        return None
    expires, payload = hit
    if time.monotonic() > expires:
        _discovery_cache.pop(key, None)
        return None
    return payload


def _latest_credential_id(user: User, db: Session) -> str:
    latest = db.scalars(
        select(Credential.id)
        .where(Credential.user_id == user.id, Credential.type == "hubspot")
        .order_by(Credential.created_at.desc())
    ).first()
    if latest is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_CREDENTIAL",
                "message": "No HubSpot credential connected. Connect HubSpot first.",
            },
        )
    return latest


def _resolve_creds(user: User, db: Session, credential_id: str) -> dict[str, Any]:
    rec = db.get(Credential, credential_id)
    if rec is None or rec.user_id != user.id or rec.type != "hubspot":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_CREDENTIAL",
                "message": "HubSpot credential not found or not yours.",
            },
        )
    try:
        resolved = resolve_credentials(db, user.id, {"hubspot": rec.id})
    except CredentialError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return resolved["hubspot"]


@router.get("/objects")
async def list_hubspot_objects(
    credential_id: str | None = Query(default=None, max_length=64),
    refresh: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Standard + custom CRM object types for the connected portal."""
    cred_id = credential_id or _latest_credential_id(user, db)
    key = _discovery_key(user.id, cred_id)
    if not refresh:
        cached_payload = _cached(key)
        if cached_payload is not None:
            return ok({**cached_payload, "cached": True})

    connector = get_connector_registry().get("hubspot")
    if connector is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "HubSpot connector is not registered.",
        )
    creds = _resolve_creds(user, db, cred_id)
    # Credential reads/decryption are the only DB work here; release the
    # session so a slow HubSpot round-trip never pins a pooled connection.
    db.close()
    try:
        result = await connector.op_execute(
            "list_object_types", {}, {"credentials": {"hubspot": creds}}
        )
    except ConnectorError as exc:
        http_status = (
            status.HTTP_401_UNAUTHORIZED
            if exc.code in ("CONNECTOR_AUTH_FAILED", "CONNECTOR_NOT_CONFIGURED")
            else status.HTTP_403_FORBIDDEN
            if exc.code in ("CONNECTOR_FORBIDDEN",)
            else status.HTTP_502_BAD_GATEWAY
        )
        if http_status >= 500:
            logger.error("hubspot object discovery failed: %s", exc)
            raise HTTPException(http_status, "HubSpot request failed.") from exc
        raise HTTPException(
            http_status, detail={"code": exc.code, "message": str(exc)}
        ) from exc

    payload = result.get("output") if isinstance(result, dict) and "output" in result else result
    if not isinstance(payload, dict) or not isinstance(payload.get("objects"), list):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "BAD_DISCOVERY_RESPONSE",
                "message": "Unexpected HubSpot object discovery response.",
            },
        )
    _discovery_cache[key] = (time.monotonic() + HUBSPOT_DISCOVERY_TTL_S, payload)
    return ok({**payload, "cached": False})
