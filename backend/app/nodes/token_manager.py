"""Token Manager node — ONE universal authentication node for Flowsmith.

Handles the complete authentication lifecycle in a single node:
1. FETCH: Automatically retrieves stored credentials for (workflow_id, provider)
   from the database. If still valid, returns them immediately and completely
   skips the Login API / authentication request.
2. AUTO-REFRESH: If the token is expired but a refresh token exists, automatically
   refreshes via the provider adapter under concurrency lock, updates the database,
   and returns the new access token without calling the Login API.
3. AUTO-STORE: When receiving Login API / HTTP Request output (or when new tokens
   are supplied), automatically extracts, normalizes, encrypts, and UPSERTs
   the credentials into the database without creating duplicate records.
4. REAUTH ROUTING: If credentials are missing or refresh fails, sets
   requiresAuthentication: true to route the workflow into the Login API.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Literal

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


class TokenManagerParams(BaseModel):
    provider: str = Field(
        default="salesforce",
        description="Target provider or auth type, e.g. salesforce, google, shopify, github, slack, microsoft, custom.",
    )
    mode: Literal["auto", "fetch", "store"] = Field(
        default="auto",
        description="Operation mode: 'auto' (detects whether to fetch or store based on input), 'fetch' (always fetch), 'store' (always store).",
    )
    workflow_id: str = Field(
        default="",
        description="Optional workflow ID override. Automatically defaults to current execution workflow context.",
    )
    auto_refresh: bool = Field(
        default=True,
        description="Automatically refresh expired access tokens using the stored refresh token.",
    )
    max_recovery_attempts: int = Field(
        default=1,
        ge=0,
        le=3,
        description="Maximum refresh attempts per workflow execution.",
    )
    access_token: str = Field(
        default="",
        description="Optional access token override/mapping. In auto mode, automatically extracted from upstream node.",
    )
    refresh_token: str = Field(
        default="",
        description="Optional refresh token override/mapping.",
    )
    token_type: str = Field(
        default="Bearer",
        description="Token type, e.g. Bearer.",
    )
    scope: str = Field(
        default="",
        description="Granted permission scope string.",
    )
    expires_at: Any = Field(
        default=None,
        description="Expiration epoch seconds or ISO timestamp string.",
    )
    expires_in: float | None = Field(
        default=None,
        description="Seconds until token expiration.",
    )
    client_id: str = Field(
        default="",
        description="OAuth client ID (used for future automatic token refresh).",
    )
    client_secret: str = Field(
        default="",
        description="OAuth client secret (stored encrypted for future token refresh).",
    )
    token_url: str = Field(
        default="",
        description="OAuth token endpoint URL (used for future automatic token refresh).",
    )


def _find_val(obj: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(obj, dict):
        return None
    for k in keys:
        if k in obj and obj[k] not in (None, ""):
            return obj[k]
        for actual_k in obj.keys():
            if actual_k.lower() == k.lower() and obj[actual_k] not in (None, ""):
                return obj[actual_k]
    return None


def _extract_from_item(item: dict[str, Any]) -> dict[str, Any]:
    """Extract OAuth tokens from incoming item or its nested body/data."""
    candidates = [item]
    body = item.get("body")
    if isinstance(body, dict):
        candidates.append(body)
    elif isinstance(body, str) and body.strip().startswith("{"):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                candidates.append(parsed)
        except Exception:
            pass

    for sub in ("data", "json", "response", "auth", "records"):
        val = item.get(sub)
        if isinstance(val, dict):
            candidates.append(val)
        elif isinstance(val, list) and val and isinstance(val[0], dict):
            candidates.append(val[0])

    res: dict[str, Any] = {}
    for c in candidates:
        if "access_token" not in res:
            at = _find_val(c, ("access_token", "accessToken", "token", "session_id", "sessionId", "id_token", "authToken"))
            if at:
                res["access_token"] = str(at)
        if "refresh_token" not in res:
            rt = _find_val(c, ("refresh_token", "refreshToken"))
            if rt:
                res["refresh_token"] = str(rt)
        if "expires_in" not in res:
            ei = _find_val(c, ("expires_in", "expiresIn"))
            if ei is not None:
                res["expires_in"] = ei
        if "expires_at" not in res:
            ea = _find_val(c, ("expires_at", "expiresAt"))
            if ea is not None:
                res["expires_at"] = ea
        if "token_type" not in res:
            tt = _find_val(c, ("token_type", "tokenType"))
            if tt:
                res["token_type"] = str(tt)
        if "scope" not in res:
            sc = _find_val(c, ("scope", "scopes"))
            if sc:
                res["scope"] = str(sc)
        if "instance_url" not in res:
            iu = _find_val(c, ("instance_url", "instanceUrl"))
            if iu:
                res["instance_url"] = str(iu)
    return res


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None


def _format_output(
    workflow_id: str,
    provider: str,
    bundle: dict[str, Any] | None,
    *,
    status: str,
    source: str,
    is_valid: bool,
    updated: bool | None = None,
) -> dict[str, Any]:
    epoch = normalize_expires_at((bundle or {}).get("expires_at"))
    raw_token = (bundle or {}).get("access_token")
    raw_type = (bundle or {}).get("token_type", "Bearer") or "Bearer"
    out = {
        "workflowId": workflow_id,
        "provider": provider,
        "accessToken": raw_token,
        "access_token": raw_token,
        "Authorization": f"{raw_type} {raw_token}" if raw_token else None,
        "authorization": f"{raw_type} {raw_token}" if raw_token else None,
        "refreshToken": (bundle or {}).get("refresh_token"),
        "refresh_token": (bundle or {}).get("refresh_token"),
        "expiresAt": _iso(epoch),
        "expires_at": _iso(epoch),
        "tokenType": raw_type,
        "token_type": raw_type,
        "scope": (bundle or {}).get("scope"),
        "credentialId": (bundle or {}).get("_row_id"),
        "isValid": is_valid,
        "source": source,
        "status": status,
        "requiresAuthentication": not is_valid,
    }
    if updated is not None:
        out["saved"] = True
        out["updated"] = updated
    return out


def _node_result(formatted: dict[str, Any], is_valid: bool) -> NodeResult:
    return NodeResult(
        output_items=[formatted],
        output_by_handle={
            "valid": [formatted] if is_valid else [],
            "login": [formatted] if not is_valid else [],
            "main": [formatted],
        },
    )


@register
class TokenManagerNode(BaseNode[TokenManagerParams]):
    node_type = "token_manager"
    display_name = "Token Manager"
    version = 1
    description = "Universal token lifecycle manager: automatically fetches stored credentials, auto-refreshes expired tokens, and saves new logins to database."
    category = "Actions"
    icon = "🔑"
    parameters_schema = TokenManagerParams
    idempotency = "conditionally_idempotent"
    input_handles = ["main"]
    output_handles = ["valid", "login"]

    async def run(
        self,
        ctx: NodeContext,
        params: TokenManagerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from app.auth_state.service import get_state, locked_refresh, mark_failed, upsert_state
        from app.db import get_session

        wf_id = (params.workflow_id or ctx.workflow_id or "").strip()
        provider = canonical_provider(params.provider or "salesforce")
        if not provider:
            raise NodeExecutionError(
                "Token Manager requires a valid provider name.",
                code="AUTH_PROVIDER_NOT_SUPPORTED",
                node_id=self.node_type,
                retryable=False,
            )

        # -------------------------------------------------------------
        # 1. Determine whether this invocation is a STORE or a FETCH
        # -------------------------------------------------------------
        auto_data: dict[str, Any] = {}
        if input_items:
            auto_data = _extract_from_item(input_items[0])

        has_incoming_token = bool((params.access_token or "").strip() or auto_data.get("access_token"))
        is_store_mode = (params.mode == "store") or (params.mode == "auto" and has_incoming_token)

        # -------------------------------------------------------------
        # 2. STORE ACTION (Save / Update Credentials to Database)
        # -------------------------------------------------------------
        if is_store_mode:
            access_token = (params.access_token or "").strip() or auto_data.get("access_token") or ""
            if not access_token:
                raise NodeExecutionError(
                    "Token Manager store action could not find an access_token in input or parameters.",
                    code="AUTH_STORAGE_FAILED",
                    node_id=self.node_type,
                    retryable=False,
                )

            refresh_token = (params.refresh_token or "").strip() or auto_data.get("refresh_token") or ""
            token_type = (params.token_type or "").strip() or auto_data.get("token_type") or "Bearer"
            scope = (params.scope or "").strip() or auto_data.get("scope") or ""

            raw_expires_at = params.expires_at if params.expires_at not in (None, "") else auto_data.get("expires_at")
            raw_expires_in = params.expires_in if params.expires_in is not None else auto_data.get("expires_in")

            epoch = normalize_expires_at(raw_expires_at)
            if epoch is None and raw_expires_in:
                try:
                    epoch = time.time() + float(raw_expires_in)
                except (TypeError, ValueError):
                    epoch = None

            bundle = {
                "access_token": access_token,
                "refresh_token": refresh_token or None,
                "token_type": token_type,
                "scope": scope or None,
                "expires_at": epoch,
                "client_id": params.client_id or None,
                "client_secret": params.client_secret or None,
                "token_url": params.token_url or None,
            }
            if auto_data.get("instance_url"):
                bundle["instance_url"] = auto_data["instance_url"]

            column_ts = datetime.fromtimestamp(epoch, UTC) if epoch else None

            db = get_session()
            try:
                row_id, created = upsert_state(
                    db, wf_id, provider, bundle, expires_at=column_ts,
                )
            except Exception as exc:
                raise NodeExecutionError(
                    f"Token Manager could not persist credentials: {exc}",
                    code="AUTH_STORAGE_FAILED",
                    node_id=self.node_type,
                    retryable=True,
                ) from exc
            finally:
                db.close()

            bundle["_row_id"] = row_id
            ctx.logger.info(
                "token manager: stored credentials for workflow=%s provider=%s (created=%s)",
                wf_id, provider, created,
            )
            formatted = _format_output(
                wf_id, provider, bundle,
                status="STORED", source="stored_credentials", is_valid=True, updated=not created,
            )
            return _node_result(formatted, is_valid=True)

        # -------------------------------------------------------------
        # 3. FETCH ACTION (Retrieve / Validate / Auto-Refresh)
        # -------------------------------------------------------------
        db = get_session()
        try:
            state = get_state(db, wf_id, provider)
        finally:
            db.close()

        # First run / No credentials exist in database
        if state is None:
            ctx.logger.info(
                "token manager: workflow=%s provider=%s status=MISSING (auth required)",
                wf_id, provider,
            )
            formatted = _format_output(
                wf_id, provider, None,
                status="MISSING", source="none", is_valid=False,
            )
            return _node_result(formatted, is_valid=False)

        epoch = normalize_expires_at(state.get("expires_at"))

        # Stored credentials are still valid -> reuse them! DO NOT call Login API!
        if not is_expired(epoch):
            ctx.logger.info(
                "token manager: workflow=%s provider=%s status=VALID (reusing stored token, skipping login)",
                wf_id, provider,
            )
            formatted = _format_output(
                wf_id, provider, state,
                status="VALID", source="stored_credentials", is_valid=True,
            )
            return _node_result(formatted, is_valid=True)

        # Token is expired -> attempt automatic single-flight refresh
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
                    "token manager: workflow=%s provider=%s status=REFRESHED (skipping login)",
                    wf_id, provider,
                )
                formatted = _format_output(
                    wf_id, provider, state,
                    status="REFRESHED", source="refreshed", is_valid=True,
                )
                return _node_result(formatted, is_valid=True)
            last_error = "AUTH_REFRESH_FAILED"
            break

        # Refresh failed or refresh token missing -> mark re-auth required
        db = get_session()
        try:
            mark_failed(db, wf_id, provider, last_error or "AUTH_REAUTH_REQUIRED")
        finally:
            db.close()

        ctx.logger.info(
            "token manager: workflow=%s provider=%s status=REAUTH_REQUIRED (routing to Login API)",
            wf_id, provider,
        )
        formatted = _format_output(
            wf_id, provider, state,
            status="REAUTH_REQUIRED", source="stored_credentials", is_valid=False,
        )
        return _node_result(formatted, is_valid=False)
