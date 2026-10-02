"""Auth Store node — persist workflow auth bundles (auth lifecycle).

Receives tokens (typically mapped from a Login API / HTTP Request step)
and upserts them encrypted under (running workflow, provider). The
workflow id always comes from the execution context — never user input.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.auth_state.adapter import canonical_provider, normalize_expires_at
from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult


class AuthStoreParams(BaseModel):
    provider: str = Field(min_length=1, description="e.g. salesforce, google, github, custom.")
    access_token: str = Field(min_length=1, description="Access token (usually mapped from login output).")
    refresh_token: str = Field(default="", description="Refresh token, if the provider issued one.")
    token_type: str = Field(default="Bearer", description="Token type.")
    scope: str = Field(default="", description="Granted scope string.")
    expires_at: Any = Field(default=None, description="Epoch seconds or ISO timestamp.")
    expires_in: float | None = Field(default=None, description="Seconds until expiry (alternative).")
    client_id: str = Field(default="", description="OAuth client id (needed for future refreshes).")
    client_secret: str = Field(default="", description="OAuth client secret (stored encrypted).")
    token_url: str = Field(default="", description="OAuth token endpoint (needed for future refreshes).")


class AuthStoreNode(BaseNode[AuthStoreParams]):
    node_type = "auth_store"
    display_name = "Auth Store"
    version = 1
    description = "Securely store workflow auth tokens (encrypted upsert)."
    category = "Actions"
    icon = "token_store"
    parameters_schema = AuthStoreParams
    idempotency = "conditionally_idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: AuthStoreParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from app.auth_state.service import upsert_state
        from app.db import get_session

        provider = canonical_provider(params.provider)
        if not provider:
            raise NodeExecutionError(
                "Auth Store needs a provider.",
                code="AUTH_PROVIDER_NOT_SUPPORTED", node_id="auth_store", retryable=False,
            )
        epoch = normalize_expires_at(params.expires_at)
        if epoch is None and params.expires_in:
            try:
                epoch = time.time() + float(params.expires_in)
            except (TypeError, ValueError):
                epoch = None
        bundle = {
            "access_token": params.access_token,
            "refresh_token": params.refresh_token or None,
            "token_type": params.token_type or "Bearer",
            "scope": params.scope or None,
            "expires_at": epoch,
            "client_id": params.client_id or None,
            "client_secret": params.client_secret or None,
            "token_url": params.token_url or None,
        }
        column_ts = datetime.fromtimestamp(epoch, UTC) if epoch else None
        db = get_session()
        try:
            row_id, created = upsert_state(
                db, ctx.workflow_id, provider, bundle, expires_at=column_ts,
            )
        except Exception as exc:
            raise NodeExecutionError(
                "Auth Store could not persist credentials.",
                code="AUTH_STORAGE_FAILED", node_id="auth_store", retryable=True,
            ) from exc
        finally:
            db.close()
        ctx.logger.info(
            "auth stored: workflow=%s provider=%s created=%s",
            ctx.workflow_id, provider, created,
        )
        return NodeResult(output_items=[{
            "saved": True,
            "workflowId": ctx.workflow_id,
            "provider": provider,
            "credentialId": row_id,
            "updated": not created,
            "accessToken": params.access_token,
            "refreshToken": params.refresh_token or None,
            "expiresAt": datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None,
            "tokenType": params.token_type or "Bearer",
            "scope": params.scope or None,
            "isValid": True,
            "source": "auth_store",
            "status": "STORED",
            "requiresAuthentication": False,
        }])
