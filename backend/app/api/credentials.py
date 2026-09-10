"""Credential endpoints (spec 9): list metadata, create, delete, types, providers, testing.

Never returns decrypted data (spec 12.1, 29): responses carry only
`{id, name, type}`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import CREDENTIAL_CREATE, CREDENTIAL_DELETE, log_event
from app.credentials import service
from app.credentials.provider_registry import get_provider_registry
from app.credentials.registry import PREDEFINED_CREDENTIALS, list_types
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


def _connector_live_test(cred_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Live-test via the connector declaring this credential type.

    Returns the probe result, or None when no connector implements
    test_connection (caller falls back to schema validation). Secrets
    never appear: probes return fixed-shape results only.
    """
    import asyncio

    from app.connectors import get_registry

    registry = get_registry()
    for info in registry.list_all():
        definition = registry.get_definition(info.connector_id)
        if definition is None or cred_type not in (definition.credential_types or {}):
            continue
        instance = registry.get(info.connector_id)
        probe: Any = getattr(instance, "test_connection", None)
        if not callable(probe):
            continue
        try:
            coro: Any = probe(dict(data))
            result = asyncio.new_event_loop().run_until_complete(coro)
        except Exception:
            return {"ok": False, "message": "Connection failed."}
        if not isinstance(result, dict):
            return {"ok": False, "message": "Connection failed."}
        return {"ok": bool(result.get("ok")), "message": str(result.get("message") or "")}
    return None


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1)
    data: dict[str, Any]


@router.get("")
def list_credentials(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return ok(service.list_for_user(db, user.id))


@router.get("/types")
def credential_types(user: User = Depends(get_current_user)) -> dict:
    return ok(list_types())


@router.get("/providers")
def credential_providers(user: User = Depends(get_current_user)) -> dict:
    """List auth providers (generic + capability report)."""
    reg = get_provider_registry()
    return ok(reg.list())


@router.get("/predefined")
def predefined_credentials(user: User = Depends(get_current_user)) -> dict:
    """List predefined credential types with implemented flag."""
    return ok(PREDEFINED_CREDENTIALS)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_credential(
    body: CredentialCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        meta = service.create_for_user(db, user.id, body.name, body.type, body.data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    log_event(db, CREDENTIAL_CREATE, target_type="credential", target_id=meta["id"], user_id=user.id)
    return ok(meta)


@router.post("/{credential_id}/test")
def test_credential(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Test a credential's validity without exposing secrets (spec 12)."""
    from app.credentials.credential_store import get_credential_store
    from app.credentials.registry import CREDENTIAL_PROVIDER, get_provider_for_type

    store = get_credential_store()
    try:
        rec = store.get_encrypted(db, user.id, credential_id)
    except service.CredentialError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    try:
        data = store.decrypt(rec)
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Cannot decrypt credential: {exc}")
    provider_id = CREDENTIAL_PROVIDER.get(rec.type) or get_provider_for_type(rec.type) or rec.type
    reg = get_provider_registry()
    provider = reg.get(provider_id) or reg.get_by_auth_type(provider_id)
    if provider is None:
        # Product connectors (Batch B+): live probe through the connector
        # owning this credential type, when it implements test_connection.
        live = _connector_live_test(rec.type, data)
        if live is not None:
            return ok({**live, "provider": rec.type})
        # Fallback: try authType from credential type registry
        from app.credentials.registry import CREDENTIAL_TYPES
        # Generic test: just validate via schema
        try:
            from app.credentials.registry import validate_data
            validate_data(rec.type, data)
            return ok({"ok": True, "message": "Credential schema valid.", "provider": provider_id or rec.type})
        except Exception as e:
            return ok({"ok": False, "message": str(e), "provider": provider_id or rec.type})
    # Redact before returning
    result = provider.testConnection(data)
    # Ensure no secrets leak
    sanitized = provider.sanitize(data) if hasattr(provider, "sanitize") else {}
    # Do not return sanitized secrets, just ok/message and non-secret provider info
    return ok({**result, "provider": provider_id, "implemented": bool(getattr(provider, "implemented", True))})


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.delete_for_user(db, user.id, credential_id)
    except service.CredentialError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    log_event(db, CREDENTIAL_DELETE, target_type="credential", target_id=credential_id, user_id=user.id)
