"""Provider-side webhook registration endpoints."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.access import get_permission, get_workflow
from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import log_event
from app.config import get_settings
from app.credentials.service import CredentialError, resolve_credentials
from app.db import get_db
from app.models import ProviderWebhookRegistration, User, WebhookTrigger
from app.schemas.workflow import Workflow
from app.security.crypto import encrypt_text
from app.services.provider_webhooks import (
    PROVIDER_BY_NODE,
    ProviderWebhookError,
    register_provider_webhook,
    unregister_provider_webhook,
)
from app.triggers.paths import validate_trigger_path

logger = logging.getLogger("provider_webhooks")

router = APIRouter(prefix="/api/provider-webhooks", tags=["provider-webhooks"])

MAX_PROVIDER_CONFIG_KEYS = 32
MAX_PROVIDER_CONFIG_STRING = 4096
MAX_PROVIDER_CONFIG_LIST = 50
MAX_PROVIDER_EVENT_LENGTH = 256


def _validate_config_bounds(config: dict[str, Any]) -> None:
    if len(config) > MAX_PROVIDER_CONFIG_KEYS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Provider config may contain at most {MAX_PROVIDER_CONFIG_KEYS} keys.",
        )
    for key, value in config.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 128:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Provider config keys must be non-empty strings of at most 128 characters.",
            )
        if isinstance(value, list):
            if len(value) > MAX_PROVIDER_CONFIG_LIST:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Provider config list '{key}' may contain at most {MAX_PROVIDER_CONFIG_LIST} items.",
                )
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        f"Provider config list '{key}' must contain non-empty strings.",
                    )
                if len(item) > MAX_PROVIDER_EVENT_LENGTH:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        f"Provider config item in '{key}' exceeds {MAX_PROVIDER_EVENT_LENGTH} characters.",
                    )
        elif isinstance(value, str):
            if len(value) > MAX_PROVIDER_CONFIG_STRING:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Provider config value '{key}' exceeds {MAX_PROVIDER_CONFIG_STRING} characters.",
                )
        elif not isinstance(value, (bool, int, float)) and value is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Provider config value '{key}' must be a string, number, boolean, or list of strings.",
            )


class RegisterWebhookRequest(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=64)
    node_id: str = Field(min_length=1, max_length=64)
    credential_id: str = Field(min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    signing_secret: str | None = Field(default=None, max_length=256)


def _registration_dict(
    row: ProviderWebhookRegistration, *, include_error: bool = True
) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "node_id": row.node_id,
        "provider": row.provider,
        "callback_url": row.callback_url,
        "external_id": row.external_id,
        "provider_config": row.provider_config or {},
        "status": row.status,
        "last_error": row.last_error if include_error else None,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


def _workflow_node(rec: Any, node_id: str) -> Any:
    workflow = Workflow.model_validate(rec.data)
    for node in workflow.nodes:
        if node.id == node_id:
            return node
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Trigger node not found.")


def _callback_url(trigger_path: str) -> str:
    base = (get_settings().public_url or "").strip().rstrip("/")
    if not base:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "PUBLIC_URL must be configured to register provider webhooks.",
        )
    if get_settings().app_env == "production" and not base.startswith("https://"):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "PUBLIC_URL must use HTTPS in production for provider webhooks.",
        )
    return f"{base}/api/webhooks/{trigger_path}"


@router.get("")
def list_provider_webhooks(
    workflow_id: str = Query(..., min_length=1, max_length=64),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_workflow(db, workflow_id, user, require_edit=False)
    permission = get_permission(db, workflow_id, user)
    include_error = permission in ("owner", "edit")
    rows = db.execute(
        select(ProviderWebhookRegistration).where(
            ProviderWebhookRegistration.workflow_id == workflow_id
        )
    ).scalars().all()
    return ok([
        _registration_dict(row, include_error=include_error) for row in rows
    ])


@router.post("/register")
async def register_webhook(
    body: RegisterWebhookRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rec = get_workflow(db, body.workflow_id, user, require_edit=True)
    if not rec.active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Activate the workflow before registering a provider webhook.",
        )
    node = _workflow_node(rec, body.node_id)
    provider = PROVIDER_BY_NODE.get(node.type)
    if provider is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Node type '{node.type}' does not support automatic provider registration.",
        )
    if provider == "slack":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Slack Events API registration is configured in the Slack app dashboard, not via API.",
        )

    params = node.parameters or {}
    trigger_path = str(params.get("path") or "").strip()
    if not trigger_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Trigger path is required.")
    try:
        trigger_path = validate_trigger_path(node.type, trigger_path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    conflicting_trigger = db.scalar(
        select(WebhookTrigger).where(
            WebhookTrigger.path == trigger_path,
            WebhookTrigger.workflow_id != body.workflow_id,
        )
    )
    if conflicting_trigger is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Trigger path is already used by another active workflow.",
        )
    existing = db.scalar(
        select(ProviderWebhookRegistration).where(
            ProviderWebhookRegistration.workflow_id == body.workflow_id,
            ProviderWebhookRegistration.node_id == body.node_id,
            ProviderWebhookRegistration.provider == provider,
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This provider webhook is already registered. Delete the existing registration first.",
        )

    try:
        resolved = resolve_credentials(db, user.id, {provider: body.credential_id})
    except CredentialError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    credential = resolved.get(provider)
    if not isinstance(credential, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Credential data could not be resolved.")

    merge_config = params.get("provider_config")
    config = dict(merge_config) if isinstance(merge_config, dict) else {}
    config.update(body.config or {})
    _validate_config_bounds(config)
    node_secret = str(params.get("secret") or "").strip()
    signing_secret = (body.signing_secret or "").strip() or node_secret or None
    if provider in ("github", "gitlab", "typeform") and not signing_secret:
        signing_secret = secrets.token_hex(32)
    if provider == "shopify" and not signing_secret:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Shopify requires the app client secret for HMAC verification.",
        )

    callback = _callback_url(trigger_path)
    try:
        result = await register_provider_webhook(
            provider=provider,
            credential=credential,
            callback_url=callback,
            config=config,
            signing_secret=signing_secret,
        )
    except ProviderWebhookError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    row = ProviderWebhookRegistration(
        id=f"pwh_{secrets.token_hex(12)}",
        workflow_id=body.workflow_id,
        user_id=user.id,
        node_id=body.node_id,
        provider=provider,
        credential_id=body.credential_id,
        callback_url=callback,
        external_id=result.external_id,
        provider_config=result.provider_config,
        signing_secret=encrypt_text(result.signing_secret) if result.signing_secret else None,
        status="active",
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        # Do not leave an orphaned provider-side webhook if the local row
        # could not be committed (for example a concurrent registration).
        try:
            await unregister_provider_webhook(
                provider=provider,
                credential=credential,
                external_id=result.external_id,
                config=result.provider_config,
            )
        except Exception:
            logger.exception("could not roll back provider webhook %s", result.external_id)
        raise
    log_event(
        db,
        "provider_webhook.registered",
        target_type="provider_webhook",
        target_id=row.id,
        user_id=user.id,
        detail={"workflow_id": body.workflow_id, "node_id": body.node_id, "provider": provider},
    )
    return ok(_registration_dict(row))


@router.delete("/{registration_id}")
async def unregister_webhook(
    registration_id: str,
    force: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(ProviderWebhookRegistration, registration_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider webhook registration not found.")
    get_workflow(db, row.workflow_id, user, require_edit=True)
    provider = row.provider
    try:
        resolved = resolve_credentials(db, row.user_id, {provider: row.credential_id})
        credential = resolved.get(provider)
        if not isinstance(credential, dict):
            raise CredentialError("Credential data could not be resolved.")
        await unregister_provider_webhook(
            provider=provider,
            credential=credential,
            external_id=str(row.external_id or ""),
            config=row.provider_config or {},
        )
    except (CredentialError, ProviderWebhookError) as exc:
        if not force:
            row.status = "error"
            row.last_error = str(exc)[:1000]
            db.commit()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        # Keep the local row so the reaper can retry the provider-side
        # deletion.  Deleting the row here would permanently orphan the
        # provider webhook and keep sending events to a dead callback.
        row.status = "orphaned"
        row.last_error = str(exc)[:1000]
        db.commit()
        logger.warning("queued provider webhook cleanup %s after unregister error: %s", row.id, exc)
        log_event(
            db,
            "provider_webhook.cleanup_queued",
            target_type="provider_webhook",
            target_id=row.id,
            user_id=user.id,
            detail={"workflow_id": row.workflow_id, "provider": provider},
        )
        return ok({
            "id": row.id,
            "unregistered": False,
            "cleanup_pending": True,
            "status": "orphaned",
        })

    except Exception as exc:
        # Network/protocol failures can escape the provider adapter.  Never
        # delete the local row on force: queue the same reaper-owned cleanup.
        if not force:
            row.status = "error"
            row.last_error = "Provider cleanup failed."
            db.commit()
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Provider cleanup failed."
            ) from exc
        row.status = "orphaned"
        row.last_error = "Provider cleanup failed; retry scheduled."
        db.commit()
        logger.exception("queued provider webhook cleanup %s after unexpected error", row.id)
        log_event(
            db,
            "provider_webhook.cleanup_queued",
            target_type="provider_webhook",
            target_id=row.id,
            user_id=user.id,
            detail={"workflow_id": row.workflow_id, "provider": provider},
        )
        return ok({
            "id": row.id,
            "unregistered": False,
            "cleanup_pending": True,
            "status": "orphaned",
        })

    target = row.id
    db.delete(row)
    db.commit()
    log_event(
        db,
        "provider_webhook.unregistered",
        target_type="provider_webhook",
        target_id=target,
        user_id=user.id,
        detail={"workflow_id": row.workflow_id},
    )
    return ok({"id": target, "unregistered": True})
