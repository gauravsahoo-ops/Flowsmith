"""Token Fetch node — retrieve workflow authentication tokens.

Automatically resolves authentication state for (workflow_id, provider).
Workflow ID is automatically retrieved from the execution context (or can
be specified). If tokens are missing or cannot be refreshed, marks
requiresAuthentication: true to route into Login API / HTTP Request.
If valid or successfully refreshed, returns valid access/refresh tokens.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.auth_state.adapter import (
    canonical_provider,
    is_expired,
    mask_token,
    normalize_expires_at,
    refresh_bundle,
)
from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class TokenFetchParams(BaseModel):
    provider: str = Field(
        default="salesforce",
        min_length=1,
        description="Provider or auth type, e.g. salesforce, google, shopify, github, slack, microsoft, custom.",
    )
    workflow_id: str = Field(
        default="",
        description="Optional workflow ID override. Defaults automatically to current execution workflow.",
    )
    auto_refresh: bool = Field(
        default=True,
        description="Automatically attempt single-flight token refresh if expired.",
    )
    max_recovery_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Maximum refresh attempts per workflow execution.",
    )


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None


def _output(
    workflow_id: str,
    provider: str,
    bundle: dict[str, Any] | None,
    *,
    status: str,
    source: str,
    is_valid: bool,
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


class TokenFetchNode(BaseNode[TokenFetchParams]):
    node_type = "token_fetch"
    display_name = "Token Fetch"
    version = 1
    description = "Automatically retrieve stored authentication for the workflow, refreshing once when expired."
    category = "Actions"
    icon = "🔑"
    parameters_schema = TokenFetchParams

    async def run(
        self,
        ctx: NodeContext,
        params: TokenFetchParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from app.auth_state.service import get_state, locked_refresh, mark_failed
        from app.db import get_session

        wf_id = (params.workflow_id or ctx.workflow_id or "").strip()
        provider = canonical_provider(params.provider)
        if not provider:
            raise NodeExecutionError(
                "Token Fetch requires a provider name (e.g. salesforce, google, github, custom).",
                code="AUTH_PROVIDER_NOT_SUPPORTED",
                node_id=self.node_type,
                retryable=False,
            )

        db = get_session()
        try:
            state = get_state(db, wf_id, provider)
        finally:
            db.close()

        # First execution or missing record
        if state is None:
            ctx.logger.info(
                "token fetch: workflow=%s provider=%s status=MISSING",
                wf_id, provider,
            )
            return NodeResult(
                output_items=[
                    _output(
                        wf_id, provider, None,
                        status="MISSING", source="none", is_valid=False,
                    )
                ]
            )

        epoch = normalize_expires_at(state.get("expires_at"))
        # Stored credentials still valid
        if not is_expired(epoch):
            ctx.logger.info(
                "token fetch: workflow=%s provider=%s status=VALID",
                wf_id, provider,
            )
            return NodeResult(
                output_items=[
                    _output(
                        wf_id, provider, state,
                        status="VALID", source="stored_credentials", is_valid=True,
                    )
                ]
            )

        # Expired: single-flight refresh with recheck under lock
        attempts = 0
        last_error = ""
        while attempts < max(params.max_recovery_attempts, 1):
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
                    fresh = await locked_refresh(db, wf_id, provider, _do_refresh)
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
                    "token fetch: workflow=%s provider=%s status=REFRESHED attempts=%d",
                    wf_id, provider, attempts,
                )
                return NodeResult(
                    output_items=[
                        _output(
                            wf_id, provider, state,
                            status="REFRESHED", source="refreshed", is_valid=True,
                        )
                    ]
                )
            last_error = "AUTH_REFRESH_FAILED"
            break

        db = get_session()
        try:
            mark_failed(db, wf_id, provider, last_error or "AUTH_REAUTH_REQUIRED")
        finally:
            db.close()

        ctx.logger.info(
            "token fetch: workflow=%s provider=%s status=REAUTH_REQUIRED reason=%s",
            wf_id, provider, last_error or "none",
        )
        return NodeResult(
            output_items=[
                _output(
                    wf_id, provider, state,
                    status="REAUTH_REQUIRED", source="stored_credentials", is_valid=False,
                )
            ]
        )
