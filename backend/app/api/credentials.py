"""Credential endpoints (spec 9): list metadata, create, delete, types, providers, testing.

Never returns decrypted data (spec 12.1, 29): responses carry only
`{id, name, type}`.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import CREDENTIAL_CREATE, CREDENTIAL_DELETE, CREDENTIAL_RECONNECT, log_event
from app.credentials import service
from app.credentials.provider_registry import get_provider_registry
from app.credentials.registry import PREDEFINED_CREDENTIALS, list_types
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api/credentials", tags=["credentials"])

logger = logging.getLogger("api.credentials")


async def _connector_live_test(cred_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Live-test via the connector declaring this credential type.

    Returns the probe result, or None when no connector implements
    test_connection (caller falls back to schema validation). Secrets
    never appear: probes return fixed-shape results only.

    Async-safe: awaits awaitable probes on the running loop instead of
    spinning up a nested event loop.
    """
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
            result = probe(dict(data))
            if inspect.isawaitable(result):
                result = await result
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


@router.get("/auth-metadata")
def credential_auth_metadata(user: User = Depends(get_current_user)) -> dict:
    """Return machine-readable authentication metadata and classification summary across all connectors."""
    from app.credentials.auth_metadata import list_connector_auth_metadata, get_auth_classification_summary

    items = list_connector_auth_metadata()
    summary = get_auth_classification_summary()
    return ok({
        "connectors": [i.model_dump() for i in items],
        "summary": summary,
    })


@router.post("", status_code=status.HTTP_201_CREATED)
def create_credential(
    body: CredentialCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.credentials.registry import is_implemented

    if not is_implemented(body.type):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Connector '{body.type}' unavailable — implementation pending."
        )

    try:
        meta = service.create_for_user(db, user.id, body.name, body.type, body.data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    log_event(db, CREDENTIAL_CREATE, target_type="credential", target_id=meta["id"], user_id=user.id)
    return ok(meta)


class CredentialUpdateBody(BaseModel):
    name: str | None = None
    data: dict[str, Any] | None = None


@router.put("/{credential_id}")
@router.patch("/{credential_id}")
def update_credential(
    credential_id: str,
    body: CredentialUpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Rotate/update credential name or secrets without changing its credential ID, preserving workflows."""
    try:
        meta = service.update_for_user(db, user.id, credential_id, name=body.name, data=body.data)
    except service.CredentialError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return ok(meta)



@router.post("/{credential_id}/reconnect")
async def reconnect_credential_endpoint(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Explicitly trigger background reconnection / token renewal for a credential."""
    from app.credentials.auto_reconnect import reconnect_credential

    res = await reconnect_credential(db, user.id, credential_id)
    if res.get("code") == "NOT_FOUND":
        raise HTTPException(status.HTTP_404_NOT_FOUND, res.get("message", "Not found"))
    if res.get("ok"):
        try:
            log_event(db, CREDENTIAL_RECONNECT, target_type="credential",
                      target_id=credential_id, user_id=user.id)
        except Exception:
            logger.exception("audit log failed for credential reconnect")
    return ok(res)


class CredentialUpdateConfig(BaseModel):
    name: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    login_url: str | None = None
    instance_url: str | None = None
    private_token: str | None = None


class OAuthConfigPayload(BaseModel):
    client_id: str
    client_secret: str
    login_url: str | None = None
    redirect_uri: str | None = None


@router.get("/oauth-config/{provider}")
def get_oauth_provider_config(
    provider: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Check if OAuth Connected App credentials exist in database for this provider."""
    import json
    from sqlalchemy import select
    from app.models.credential import Credential
    from app.security.crypto import decrypt_text
    from app.oauth_providers import get_provider

    try:
        spec = get_provider(provider)
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown OAuth provider: {provider}")

    prefix = spec.config_prefix or spec.key
    types_to_check = [
        f"{provider}_oauth_config",
        f"{spec.credential_type}_oauth_config",
        f"{prefix}_oauth_config",
        spec.credential_type,
        provider,
        prefix,
    ]
    query = select(Credential).where(
        Credential.type.in_(types_to_check)
    )
    candidates = list(
        db.scalars(query.where(Credential.user_id == user.id).order_by(Credential.created_at.desc())).all()
    )
    if not candidates:
        # Fallback to shared connected-app config only — never other users'
        # per-connection credential rows.
        config_types = [t for t in types_to_check if t.endswith("_oauth_config")]
        candidates = list(
            db.scalars(query.where(Credential.type.in_(config_types)).order_by(Credential.created_at.desc())).all()
        )

    for cand in candidates:
        try:
            data = json.loads(decrypt_text(cand.data))
            cid = (data.get("client_id") or "").strip()
            csec = (data.get("client_secret") or "").strip()
            if cid and csec:
                masked_cid = f"{cid[:8]}...{cid[-4:]}" if len(cid) > 12 else cid
                r_uri = (data.get("redirect_uri") or "").strip()
                if not r_uri:
                    try:
                        from app.config import get_settings
                        _, _, r_uri = spec.server_config(get_settings(), db=db, user_id=user.id, client_id=cid, client_secret=csec)
                    except Exception:
                        pass
                return ok({
                    "configured": True,
                    "client_id": cid,
                    "client_id_preview": masked_cid,
                    "has_secret": True,
                    "login_url": data.get("login_url") or "",
                    "instance_url": data.get("instance_url") or "",
                    "redirect_uri": r_uri,
                    "source": "database",
                })
        except Exception:
            continue

    # Fallback to server configuration (Settings / .env)
    from app.config import get_settings
    settings = get_settings()
    prefix = spec.config_prefix or spec.key
    s_cid = getattr(settings, f"{prefix}_client_id", "") or ""
    s_sec = getattr(settings, f"{prefix}_client_secret", "") or ""
    s_login = getattr(settings, f"{prefix}_login_url", "") or ""
    s_redirect = getattr(settings, f"{prefix}_redirect_uri", "") or ""
    if not s_redirect:
        base = (getattr(settings, "public_url", "") or "").rstrip("/")
        if base:
            s_redirect = f"{base}/api/auth/{spec.key}/callback"
        else:
            s_redirect = f"https://flowsmith.dev.idslogic.net/api/auth/{spec.key}/callback"

    if s_cid:
        masked_cid = f"{s_cid[:8]}...{s_cid[-4:]}" if len(s_cid) > 12 else s_cid
        return ok({
            "configured": True,
            "client_id": s_cid,
            "client_id_preview": masked_cid,
            "has_secret": bool(s_sec),
            "login_url": s_login,
            "redirect_uri": s_redirect,
            "source": "environment",
        })

    return ok({
        "configured": False,
        "client_id": "",
        "client_id_preview": "",
        "has_secret": False,
        "login_url": s_login,
        "redirect_uri": s_redirect,
        "source": None,
    })


@router.post("/oauth-config/{provider}")
def save_oauth_provider_config(
    provider: str,
    body: OAuthConfigPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Save or update OAuth Connected App credentials in the database (Fernet-encrypted)."""
    import json
    import secrets
    from sqlalchemy import select
    from app.models.credential import Credential
    from app.security.crypto import decrypt_text, encrypt_text
    from app.oauth_providers import get_provider

    try:
        spec = get_provider(provider)
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown OAuth provider: {provider}")

    cid = body.client_id.strip()
    csec = body.client_secret.strip()
    if not cid or not csec:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "client_id and client_secret are required.")

    config_type = f"{provider}_oauth_config"
    if provider.startswith("google_") or provider == "google":
        config_type = "google_oauth_config"

    existing = db.scalars(
        select(Credential).where(
            Credential.type == config_type,
            Credential.user_id == user.id,
        )
    ).first()

    data_payload = {
        "client_id": cid,
        "client_secret": csec,
        "login_url": (body.login_url or "").strip(),
        "redirect_uri": (body.redirect_uri or "").strip(),
    }

    if existing:
        existing.data = encrypt_text(json.dumps(data_payload, ensure_ascii=False))
        db.commit()
        db.refresh(existing)
    else:
        new_rec = Credential(
            id=f"cfg_{secrets.token_hex(6)}",
            user_id=user.id,
            name=f"{spec.display_name} Connected App (Database Config)",
            type=config_type,
            data=encrypt_text(json.dumps(data_payload, ensure_ascii=False)),
        )
        db.add(new_rec)
        db.commit()

    # Backfill any existing credentials of this type that have empty client_id/secret
    cred_types_to_update = [spec.credential_type]
    if provider.startswith("google_") or provider == "google":
        cred_types_to_update = [
            "google_calendar",
            "google_sheets",
            "gmail",
            "google_drive",
            "google_docs",
        ]
    creds_to_update = db.scalars(
        select(Credential).where(
            Credential.type.in_(cred_types_to_update),
            Credential.user_id == user.id,
        )
    ).all()
    for c in creds_to_update:
        try:
            c_data = json.loads(decrypt_text(c.data))
            if not c_data.get("client_id") or not c_data.get("client_secret"):
                c_data["client_id"] = cid
                c_data["client_secret"] = csec
                if body.login_url and not c_data.get("login_url"):
                    c_data["login_url"] = body.login_url.strip()
                c.data = encrypt_text(json.dumps(c_data, ensure_ascii=False))
        except Exception:
            pass
    db.commit()

    return ok({
        "configured": True,
        "message": f"{spec.display_name} Connected App credentials saved securely to database.",
    })


@router.patch("/{credential_id}/config")
def update_credential_config(
    credential_id: str,
    body: CredentialUpdateConfig,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update connection/OAuth config (client_id, client_secret, login_url) directly in the database."""
    import json
    from app.models.credential import Credential
    from app.security.crypto import decrypt_text, encrypt_text

    rec = db.get(Credential, credential_id)
    if rec is None or rec.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found.")
    try:
        data = json.loads(decrypt_text(rec.data))
    except Exception:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Cannot decrypt credential.")

    if body.name is not None and body.name.strip():
        rec.name = body.name.strip()
    if body.client_id is not None:
        data["client_id"] = body.client_id.strip()
    if body.client_secret is not None:
        data["client_secret"] = body.client_secret.strip()
    if body.login_url is not None:
        data["login_url"] = body.login_url.strip()
    if body.instance_url is not None:
        data["instance_url"] = body.instance_url.strip()
    if body.private_token is not None:
        data["private_token"] = body.private_token.strip()

    rec.data = encrypt_text(json.dumps(data, ensure_ascii=False))
    db.commit()
    db.refresh(rec)
    return ok({"id": rec.id, "name": rec.name, "type": rec.type, "message": "Credential configuration updated in database."})


@router.post("/{credential_id}/test")
async def test_credential(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Test a credential's validity without exposing secrets (spec 12).

    Side effect (documented): when the stored credential is expired or its
    live probe fails AND it supports background reconnect (refresh token /
    Salesforce password flow), the endpoint refreshes it once via
    ``reconnect_credential`` (persisting rotated tokens, audited as
    ``credential.reconnect``) and re-probes before returning.
    """
    from app.credentials.auto_reconnect import can_auto_reconnect, is_credential_expiring, reconnect_credential
    from app.credentials.credential_store import get_credential_store
    from app.credentials.registry import CREDENTIAL_PROVIDER, get_provider_for_type

    store = get_credential_store()
    try:
        rec = store.get_encrypted(db, user.id, credential_id)
    except service.CredentialError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)

    from app.credentials.registry import is_implemented
    if not is_implemented(rec.type):
        return ok({"ok": False, "message": "Connector unavailable — implementation pending.", "implemented": False, "provider": rec.type})

    try:
        data = store.decrypt(rec)
    except Exception:
        logger.warning("Cannot decrypt credential %s for test", credential_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Cannot decrypt credential.")

    # If already expired and can auto-reconnect, refresh proactively before testing
    if can_auto_reconnect(rec.type, data) and is_credential_expiring(data, window_seconds=0):
        reconn = await reconnect_credential(db, user.id, credential_id)
        if reconn.get("ok"):
            try:
                log_event(db, CREDENTIAL_RECONNECT, target_type="credential",
                          target_id=credential_id, user_id=user.id,
                          detail={"via": "test", "phase": "pre-probe"})
            except Exception:
                logger.exception("audit log failed for credential reconnect")
            try:
                rec = store.get_encrypted(db, user.id, credential_id)
                data = store.decrypt(rec)
            except Exception:
                logger.warning("Cannot re-read refreshed credential %s", credential_id)
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Cannot decrypt credential.")

    async def _run_test(target_data: dict[str, Any]) -> dict[str, Any]:
        if rec.type == "llm":
            from app.ai.llm_registry import get_llm_registry
            from app.ai.llm_adapters import get_adapter_for_provider
            prov_id = target_data.get("provider") or "openai"
            prov_def = get_llm_registry().get(prov_id) or get_llm_registry().get("custom")
            if prov_def is None:
                return {"ok": False, "error": f"Unknown LLM provider '{prov_id}'."}
            adapter = get_adapter_for_provider(prov_def)
            live_res = await adapter.test_connection(target_data, variant=target_data.get("variant", ""))
            return {**live_res, "provider": prov_id}

        provider_id = CREDENTIAL_PROVIDER.get(rec.type) or get_provider_for_type(rec.type) or rec.type
        reg = get_provider_registry()
        provider = reg.get(provider_id) or reg.get_by_auth_type(provider_id)
        if provider is None:
            # Product connectors (Batch B+): live probe through the connector
            # owning this credential type, when it implements test_connection.
            live = await _connector_live_test(rec.type, target_data)
            if live is not None:
                return {**live, "provider": rec.type}
            # Fallback: try authType from credential type registry
            # Generic test: just validate via schema
            try:
                from app.credentials.registry import validate_data
                validate_data(rec.type, target_data)
                return {"ok": True, "message": "Credential schema valid.", "provider": provider_id or rec.type}
            except Exception as e:
                return {"ok": False, "message": str(e), "provider": provider_id or rec.type}
        # Redact before returning
        result = provider.testConnection(target_data)
        if inspect.isawaitable(result):
            result = await result
        # Ensure no secrets leak
        return {**result, "provider": provider_id, "implemented": bool(getattr(provider, "implemented", True))}

    res = await _run_test(data)

    # If probe failed and can auto-reconnect, attempt re-auth/refresh and re-probe once
    if not res.get("ok") and can_auto_reconnect(rec.type, data):
        reconn = await reconnect_credential(db, user.id, credential_id)
        if reconn.get("ok"):
            try:
                log_event(db, CREDENTIAL_RECONNECT, target_type="credential",
                          target_id=credential_id, user_id=user.id,
                          detail={"via": "test", "phase": "post-probe"})
            except Exception:
                logger.exception("audit log failed for credential reconnect")
            try:
                rec = store.get_encrypted(db, user.id, credential_id)
                data = store.decrypt(rec)
            except Exception:
                logger.warning("Cannot re-read refreshed credential %s", credential_id)
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Cannot decrypt credential.")
            res = await _run_test(data)
            if res.get("ok"):
                res["message"] = f"{res.get('message', '')} (Auto-reconnected successfully)".strip()

    return ok(res)


@router.post("/{credential_id}/logout")
async def logout_credential(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Total credential logout: revokes active tokens with upstream provider and removes credential."""
    try:
        result = await service.logout_for_user(db, user.id, credential_id)
    except service.CredentialError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    log_event(
        db,
        "credential.logout",
        target_type="credential",
        target_id=credential_id,
        user_id=user.id,
        detail={"name": result.get("name"), "type": result.get("type"), "revoked": result.get("revoked")},
    )
    return ok(result)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        await service.logout_for_user(db, user.id, credential_id)
    except service.CredentialError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    log_event(db, CREDENTIAL_DELETE, target_type="credential", target_id=credential_id, user_id=user.id)

