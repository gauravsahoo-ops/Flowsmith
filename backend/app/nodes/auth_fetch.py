"""Auth Fetch node — read workflow auth state (auth lifecycle).

Resolves (running workflow, provider) automatically and returns the
stored bundle, refreshing once when expired. Auth outcomes are
Branching outputs (status/requiresAuthentication), never throws —
except misconfiguration (unknown provider). Pair with an IF node:
requiresAuthentication → Login API → Auth Store → continue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.auth_state.adapter import (
    canonical_provider,
    is_expired,
    normalize_expires_at,
    refresh_bundle,
)
from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class AuthFetchParams(BaseModel):
    provider: str = Field(min_length=1, description="e.g. salesforce, google, github, custom.")
    auto_refresh: bool = Field(default=True, description="Refresh once when expired.")
    max_recovery_attempts: int = Field(default=1, ge=0, le=3, description="Refresh tries per execution.")


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None


def _output(
    workflow_id: str, provider: str, bundle: dict[str, Any] | None,
    *, status: str, source: str, is_valid: bool,
) -> dict[str, Any]:
    epoch = normalize_expires_at((bundle or {}).get("expires_at"))
    return {
        "workflowId": workflow_id,
        "provider": provider,
        "accessToken": (bundle or {}).get("access_token"),
        "refreshToken": (bundle or {}).get("refresh_token"),
        "expiresAt": _iso(epoch),
        "tokenType": (bundle or {}).get("token_type", "Bearer"),
        "scope": (bundle or {}).get("scope"),
        "credentialId": (bundle or {}).get("_row_id"),
        "isValid": is_valid,
        "source": source,
        "status": status,
        "requiresAuthentication": not is_valid,
    }


class AuthFetchNode(BaseNode[AuthFetchParams]):
    node_type = "auth_fetch"
    display_name = "Auth Fetch"
    version = 1
    description = "Fetch stored workflow auth, refreshing once when expired."
    category = "Actions"
    icon = "🔐"
    parameters_schema = AuthFetchParams

    async def run(
        self,
        ctx: NodeContext,
        params: AuthFetchParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from app.auth_state.service import get_state, locked_refresh, mark_failed
        from app.db import get_session

        provider = canonical_provider(params.provider)
        if not provider:
            raise NodeExecutionError(
                "Auth Fetch needs a provider.",
                code="AUTH_PROVIDER_NOT_SUPPORTED", node_id="auth_fetch", retryable=False,
            )

        db = get_session()
        try:
            state = get_state(db, ctx.workflow_id, provider)
        finally:
            db.close()
        if state is None:
            ctx.logger.info("auth fetch: workflow=%s provider=%s status=MISSING", ctx.workflow_id, provider)
            return NodeResult(output_items=[_output(
                ctx.workflow_id, provider, None,
                status="MISSING", source="none", is_valid=False,
            )])

        epoch = normalize_expires_at(state.get("expires_at"))
        if not is_expired(epoch):
            ctx.logger.info("auth fetch: workflow=%s provider=%s status=VALID", ctx.workflow_id, provider)
            return NodeResult(output_items=[_output(
                ctx.workflow_id, provider, state,
                status="VALID", source="auth_store", is_valid=True,
            )])

        # Expired: single-flight refresh with recheck under lock.
        attempts = 0
        last_error = ""
        while attempts <= max(params.max_recovery_attempts, 0):
            if not params.auto_refresh:
                break
            if not str(state.get("refresh_token") or "").strip():
                last_error = "AUTH_REFRESH_FAILED"
                break
            attempts += 1
            db = get_session()
            try:
                async def _do_refresh(bundle: dict[str, Any], _provider: str = provider) -> dict[str, Any]:
                    return await refresh_bundle(_provider, bundle)

                try:
                    fresh = await locked_refresh(db, ctx.workflow_id, provider, _do_refresh)
                except NodeExecutionError as exc:
                    last_error = exc.code
                    if exc.code == "AUTH_PROVIDER_NOT_SUPPORTED":
                        raise
                    break
            finally:
                db.close()
            if fresh is None:
                last_error = "AUTH_CREDENTIAL_NOT_FOUND"
                break
            state = {**fresh, "_row_id": state.get("_row_id")}
            if not is_expired(normalize_expires_at(state.get("expires_at"))):
                ctx.logger.info(
                    "auth fetch: workflow=%s provider=%s status=REFRESHED attempts=%d",
                    ctx.workflow_id, provider, attempts,
                )
                return NodeResult(output_items=[_output(
                    ctx.workflow_id, provider, state,
                    status="REFRESHED", source="refreshed", is_valid=True,
                )])
            last_error = "AUTH_REFRESH_FAILED"
            break

        db = get_session()
        try:
            mark_failed(db, ctx.workflow_id, provider, last_error or "AUTH_REAUTH_REQUIRED")
        finally:
            db.close()
        ctx.logger.info(
            "auth fetch: workflow=%s provider=%s status=REAUTH_REQUIRED reason=%s",
            ctx.workflow_id, provider, last_error or "none",
        )
        return NodeResult(output_items=[_output(
            ctx.workflow_id, provider, state,
            status="REAUTH_REQUIRED", source="auth_store", is_valid=False,
        )])
