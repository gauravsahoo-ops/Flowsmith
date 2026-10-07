"""Live Salesforce schema/object discovery API (Phase 9).

Dynamic object/field configuration backend: the UI calls these
endpoints to populate the Salesforce node's Object picker and to show
the field reference (names, types, picklists, required flags) for the
selected object — no hard-coded object lists.

    GET /api/connectors/salesforce/objects              -> object discovery
    GET /api/connectors/salesforce/schema/{object}      -> field discovery

Both run through the registered SalesforceConnector's op_execute, so
validation, enrichment and error classification stay single-sourced.
The caller's most recent 'salesforce' credential is used unless an
explicit credential_id query parameter is supplied.

Responses are cached in-process per (user, credential, kind, object)
for SALESFORCE_DISCOVERY_TTL_S seconds — org metadata changes rarely,
and describe responses are large. Delete/rotate a credential and a new
cache key is used automatically.
"""

from __future__ import annotations

import logging
import re
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

router = APIRouter(prefix="/api/connectors/salesforce", tags=["connectors"])
logger = logging.getLogger("salesforce.discovery")

#: Metadata cache TTL (seconds).
SALESFORCE_DISCOVERY_TTL_S = 300.0

_OBJECT_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# {key: (expires_at_monotonic, payload)}; single event loop -> dict ops are safe.
_discovery_cache: dict[tuple[str, int, str, str], tuple[float, Any]] = {}


def _discovery_key(user_id: int, credential_id: str, kind: str, obj: str = "") -> tuple[str, int, str, str]:
    return ("sf-discovery", user_id, credential_id, f"{kind}:{obj}")


def clear_discovery_cache() -> None:
    """Test hook / manual invalidation."""
    _discovery_cache.clear()


def _cached(key: tuple[str, int, str, str]) -> Any | None:
    hit = _discovery_cache.get(key)
    if hit is None:
        return None
    expires, payload = hit
    if time.monotonic() > expires:
        _discovery_cache.pop(key, None)
        return None
    return payload


async def _run_salesforce_op(
    user: User,
    db: Session,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the user's Salesforce credential and run a connector op."""
    connector = get_connector_registry().get("salesforce")
    if connector is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Salesforce connector is not registered.",
        )
    creds = await _resolve_creds(user, db)
    try:
        result = await connector.op_execute(
            operation, payload, {"credentials": {"salesforce": creds}}
        )
    except ConnectorError as exc:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if exc.code in ("CONNECTOR_NOT_FOUND",)
            else status.HTTP_401_UNAUTHORIZED
            if exc.code in ("CONNECTOR_AUTH_FAILED", "CONNECTOR_NOT_CONFIGURED")
            else status.HTTP_403_FORBIDDEN
            if exc.code in ("CONNECTOR_FORBIDDEN",)
            else status.HTTP_502_BAD_GATEWAY
        )
        if http_status >= 500:
            logger.error("salesforce operation %s failed: %s", operation, exc)
            raise HTTPException(http_status, "Salesforce request failed.") from exc
        raise HTTPException(http_status, detail={"code": exc.code, "message": str(exc)}) from exc
    output = result.get("output")
    if not isinstance(output, dict):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={"code": "BAD_DISCOVERY_RESPONSE", "message": "Unexpected Salesforce response."},
        )
    return output


async def _resolve_creds(user: User, db: Session, credential_id: str | None = None) -> dict[str, Any]:
    """Decrypt the user's Salesforce credential (latest by default)."""
    if credential_id:
        rec = db.get(Credential, credential_id)
        if rec is None or rec.user_id != user.id or rec.type != "salesforce":
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"code": "NO_CREDENTIAL",
                        "message": "Salesforce credential not found or not yours."},
            )
    else:
        rec = db.scalars(
            select(Credential)
            .where(Credential.user_id == user.id, Credential.type == "salesforce")
            .order_by(Credential.created_at.desc())
        ).first()
        if rec is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "NO_CREDENTIAL",
                    "message": "No Salesforce credential connected. Connect Salesforce first.",
                },
            )
    try:
        resolved = resolve_credentials(db, user.id, {"salesforce": rec.id})
    except CredentialError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return resolved["salesforce"]


@router.get("/resources")
async def get_resource_matrix(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Single source: resource → valid operations (no credential needed)."""
    from app.connectors.salesforce_definition import RESOURCE_OPERATION_MATRIX, CURATED_OPERATION_LABELS

    return ok({"resources": RESOURCE_OPERATION_MATRIX, "labels": CURATED_OPERATION_LABELS, "operations": list({op for ops in RESOURCE_OPERATION_MATRIX.values() for op in ops})})


@router.get("/objects")
async def list_objects(
    credential_id: str | None = Query(default=None, max_length=64),
    refresh: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Object discovery: every sobject in the connected org."""
    # Cache key needs the credential id even when auto-picked.
    if credential_id:
        cred_id = credential_id
    else:
        latest = db.scalars(
            select(Credential.id)
            .where(Credential.user_id == user.id, Credential.type == "salesforce")
            .order_by(Credential.created_at.desc())
        ).first()
        if latest is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "NO_CREDENTIAL",
                    "message": "No Salesforce credential connected. Connect Salesforce first.",
                },
            )
        cred_id = latest

    key = _discovery_key(user.id, cred_id, "objects")
    if not refresh:
        cached_payload = _cached(key)
        if cached_payload is not None:
            return ok({**cached_payload, "cached": True})

    payload = await _run_salesforce_op(user, db, "list", {"resource": "Search"})
    _discovery_cache[key] = (time.monotonic() + SALESFORCE_DISCOVERY_TTL_S, payload)
    return ok({**payload, "cached": False})


@router.get("/schema/{object_name}")
async def describe_object_schema(
    object_name: str,
    credential_id: str | None = Query(default=None, max_length=64),
    refresh: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Field discovery: rich field metadata for one object."""
    if not _OBJECT_NAME_RE.fullmatch(object_name):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_OBJECT_NAME",
                    "message": "Object name must be a valid Salesforce API name."},
        )

    if credential_id:
        cred_id = credential_id
    else:
        latest = db.scalars(
            select(Credential.id)
            .where(Credential.user_id == user.id, Credential.type == "salesforce")
            .order_by(Credential.created_at.desc())
        ).first()
        if latest is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "NO_CREDENTIAL",
                    "message": "No Salesforce credential connected. Connect Salesforce first.",
                },
            )
        cred_id = latest

    key = _discovery_key(user.id, cred_id, "schema", object_name)
    if not refresh:
        cached_payload = _cached(key)
        if cached_payload is not None:
            return ok({**cached_payload, "cached": True})

    payload = await _run_salesforce_op(user, db, "describe", {"object_name": object_name})
    _discovery_cache[key] = (time.monotonic() + SALESFORCE_DISCOVERY_TTL_S, payload)
    return ok({**payload, "cached": False})
