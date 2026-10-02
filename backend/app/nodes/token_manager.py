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

from pydantic import BaseModel, Field, field_validator

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
    mode: Literal["auto", "fetch", "store", "refresh"] = Field(
        default="auto",
        description="Operation mode: 'auto' (detects whether to fetch or store based on input), 'fetch' (always fetch), 'store' (always store), 'refresh' (uses refresh token to create new access token if expired or invalid).",
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _validate_mode(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.strip().lower()
        return v or "auto"

    @field_validator("provider", mode="before")
    @classmethod
    def _validate_provider(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.strip().lower()
        return v or "salesforce"
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
    login_url: str = Field(
        default="",
        description="Optional Login / Token API endpoint to automatically call on first run when no credentials exist in database.",
    )
    login_method: str = Field(
        default="POST",
        description="HTTP method for login endpoint (POST or GET).",
    )
    login_headers: Any = Field(
        default=None,
        description="HTTP headers for login endpoint (JSON string or dictionary).",
    )
    login_body: Any = Field(
        default=None,
        description="HTTP body payload for login endpoint (JSON string or dictionary).",
    )
    force_refresh: bool = Field(
        default=False,
        description="Manual/Forced Refresh: Always refresh token using refresh token on execution, even if current token is not expired.",
    )
    refresh_url: str = Field(
        default="",
        description="Optional custom Token Refresh endpoint URL for manual token refresh.",
    )
    refresh_method: str = Field(
        default="POST",
        description="HTTP method for manual refresh endpoint (POST or GET).",
    )
    refresh_headers: Any = Field(
        default=None,
        description="HTTP headers for manual refresh endpoint (JSON string or dictionary).",
    )
    refresh_body: Any = Field(
        default=None,
        description="HTTP body payload for manual refresh endpoint (JSON string or dictionary). Can reference {{refreshToken}}.",
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
    base_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(base_item or {})
    epoch = normalize_expires_at((bundle or {}).get("expires_at"))
    raw_token = (bundle or {}).get("access_token")
    raw_type = (bundle or {}).get("token_type", "Bearer") or "Bearer"
    out.update({
        "workflowId": workflow_id,
        "provider": provider if is_valid else None,
        "accessToken": raw_token,
        "access_token": raw_token,
        "Authorization": f"{raw_type} {raw_token}" if raw_token else None,
        "authorization": f"{raw_type} {raw_token}" if raw_token else None,
        "refreshToken": (bundle or {}).get("refresh_token"),
        "refresh_token": (bundle or {}).get("refresh_token"),
        "expiresAt": _iso(epoch),
        "expires_at": _iso(epoch),
        "tokenType": raw_type if is_valid else None,
        "token_type": raw_type if is_valid else None,
        "scope": (bundle or {}).get("scope"),
        "instanceUrl": (bundle or {}).get("instance_url"),
        "instance_url": (bundle or {}).get("instance_url"),
        "credentialId": (bundle or {}).get("_row_id"),
        "isValid": is_valid,
        "source": source,
        "status": status,
        "requiresAuthentication": not is_valid,
    })
    if updated is not None:
        out["saved"] = True
        out["updated"] = updated
    return out


def _format_outputs(
    input_items: list[dict[str, Any]] | None,
    workflow_id: str,
    provider: str,
    bundle: dict[str, Any] | None,
    *,
    status: str,
    source: str,
    is_valid: bool,
    updated: bool | None = None,
) -> list[dict[str, Any]]:
    if not input_items:
        return [_format_output(workflow_id, provider, bundle, status=status, source=source, is_valid=is_valid, updated=updated, base_item=None)]
    return [
        _format_output(workflow_id, provider, bundle, status=status, source=source, is_valid=is_valid, updated=updated, base_item=item)
        for item in input_items
    ]


def _interpolate_payload(data: Any, base_item: dict[str, Any] | None, env_vars: dict[str, str] | None) -> Any:
    if isinstance(data, str):
        if "{{" in data and "}}" in data:
            try:
                from app.engine.expressions import interpolate
                return interpolate(data, base_item or {}, env_vars=env_vars or {})
            except Exception:
                return data
        return data
    elif isinstance(data, dict):
        return {k: _interpolate_payload(v, base_item, env_vars) for k, v in data.items()}
    elif isinstance(data, list):
        return [_interpolate_payload(elem, base_item, env_vars) for elem in data]
    return data


async def _resolve_login_config(
    ctx: NodeContext,
    params: TokenManagerParams,
    wf_id: str,
) -> dict[str, Any] | None:
    # 1. Explicit login_url in parameters
    url = (params.login_url or "").strip()
    if url:
        return {
            "url": url,
            "method": (params.login_method or "POST").upper(),
            "headers": params.login_headers or {"Accept": "application/json"},
            "body": params.login_body,
        }

    # 2. Check workflow definition for connected Login node (only in auto mode, never in explicit fetch or refresh mode)
    if params.mode not in ("fetch", "refresh") and wf_id:
        from app.db import get_session
        from app.models.workflow import WorkflowRecord
        db = get_session()
        try:
            wf = db.query(WorkflowRecord).filter(WorkflowRecord.id == wf_id).first()
            if wf and wf.data:
                nodes = wf.data.get("nodes", [])
                node_map = {n.get("id"): n for n in nodes if isinstance(n, dict) and n.get("id")}
                conns = wf.data.get("connections", [])
                target_node = None

                curr_id = getattr(ctx, "node_id", "")
                for c in conns:
                    if not isinstance(c, dict):
                        continue
                    if c.get("source") == curr_id and c.get("sourceHandle") == "login":
                        target_node = node_map.get(c.get("target"))
                        break

                if not target_node:
                    for n in nodes:
                        if not isinstance(n, dict):
                            continue
                        label = (n.get("settings", {}).get("label") or n.get("name") or "").lower()
                        if ("login" in label or "auth" in label) and n.get("type") in ("http_request", "http"):
                            target_node = n
                            break

                if target_node:
                    p = target_node.get("parameters", {})
                    target_url = (p.get("url") or "").strip()
                    if target_url:
                        hdrs = dict(p.get("headers") or {})
                        if not hdrs and p.get("headerParameters"):
                            hdrs = {item["name"]: item["value"] for item in p.get("headerParameters") if isinstance(item, dict) and "name" in item}
                        if not any(k.lower() == "accept" for k in hdrs):
                            hdrs["Accept"] = "application/json"

                        bdy = p.get("body")
                        if not bdy and p.get("bodyParameters"):
                            bdy = {item["name"]: item["value"] for item in p.get("bodyParameters") if isinstance(item, dict) and "name" in item}
                        elif not bdy and p.get("rawBody"):
                            bdy = p.get("rawBody")

                        return {
                            "url": target_url,
                            "method": (p.get("method") or "POST").upper(),
                            "headers": hdrs,
                            "body": bdy,
                        }
        except Exception as exc:
            ctx.logger.debug("token manager: error resolving login node: %s", exc)
        finally:
            db.close()
    return None


async def _execute_login(
    ctx: NodeContext,
    login_cfg: dict[str, Any],
    wf_id: str,
    provider: str,
    params: TokenManagerParams,
    base_item: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not getattr(ctx, "http_client", None):
        return None
    url = (login_cfg.get("url") or "").strip()
    if not url:
        return None
    method = (login_cfg.get("method") or "POST").upper()
    headers = dict(login_cfg.get("headers") or {})
    body = login_cfg.get("body")

    headers = _interpolate_payload(headers, base_item, getattr(ctx, "env_vars", None))
    body = _interpolate_payload(body, base_item, getattr(ctx, "env_vars", None))

    json_payload = None
    data_payload = None
    if isinstance(body, dict):
        json_payload = body
    elif isinstance(body, str) and body.strip():
        try:
            json_payload = json.loads(body)
        except Exception:
            data_payload = body

    req_kwargs: dict[str, Any] = {"headers": headers, "timeout": 15.0}
    if json_payload is not None:
        req_kwargs["json"] = json_payload
    elif data_payload is not None:
        req_kwargs["content"] = data_payload

    try:
        ctx.logger.info("token manager: executing auto-login call to %s", url)
        resp = await ctx.http_client.request(method, url, **req_kwargs)
        if resp.status_code < 400:
            resp_data = None
            try:
                resp_data = resp.json()
            except Exception:
                pass
            if not isinstance(resp_data, dict) and resp.text.strip().startswith("{"):
                try:
                    resp_data = json.loads(resp.text)
                except Exception:
                    pass
            if isinstance(resp_data, dict):
                extracted = _extract_from_item(resp_data)
                if extracted.get("access_token"):
                    access_token = extracted["access_token"]
                    refresh_token = extracted.get("refresh_token")
                    token_type = extracted.get("token_type") or "Bearer"
                    raw_expires_at = extracted.get("expires_at")
                    raw_expires_in = extracted.get("expires_in")

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
                        "scope": extracted.get("scope") or None,
                        "expires_at": epoch,
                        "client_id": params.client_id or None,
                        "client_secret": params.client_secret or None,
                        "token_url": params.token_url or url,
                    }
                    if extracted.get("instance_url"):
                        bundle["instance_url"] = extracted["instance_url"]

                    column_ts = datetime.fromtimestamp(epoch, UTC) if epoch else None
                    from app.db import get_session
                    from app.auth_state.service import upsert_state
                    db = get_session()
                    try:
                        row_id, created = upsert_state(
                            db, wf_id, provider, bundle, expires_at=column_ts,
                        )
                    finally:
                        db.close()
                    bundle["_row_id"] = row_id
                    ctx.logger.info(
                        "token manager: auto-login successful on first run! Stored token for wf=%s provider=%s",
                        wf_id, provider,
                    )
                    return _format_output(
                        wf_id, provider, bundle,
                        status="STORED", source="login_api", is_valid=True,
                        base_item=base_item,
                    )
    except Exception as exc:
        ctx.logger.warning("token manager: initial login attempt failed: %s", exc)
    return None


async def _execute_custom_refresh(
    ctx: NodeContext,
    params: TokenManagerParams,
    bundle: dict[str, Any],
    url: str,
) -> dict[str, Any]:
    """Execute manual custom refresh HTTP request."""
    import httpx
    refresh_token = str(bundle.get("refresh_token") or params.refresh_token or "").strip()
    if not refresh_token:
        raise NodeExecutionError(
            "No refresh token stored or provided for manual refresh.",
            code="AUTH_REFRESH_FAILED",
            node_id="token_manager",
            retryable=False,
        )

    client = getattr(ctx, "http_client", None)
    own_client = False
    if not client:
        client = httpx.AsyncClient()
        own_client = True

    try:
        method = (params.refresh_method or "POST").upper()
        headers = dict(params.refresh_headers or {})
        if not any(k.lower() == "accept" for k in headers):
            headers["Accept"] = "application/json"

        body = params.refresh_body
        if body is None or body == "":
            body = {"refresh_token": refresh_token}
        elif isinstance(body, str):
            body = body.replace("{{refreshToken}}", refresh_token).replace("{{refresh_token}}", refresh_token)
            if body.strip().startswith("{"):
                try:
                    body = json.loads(body)
                except Exception:
                    pass
        elif isinstance(body, dict):
            def _sub(v: Any) -> Any:
                if isinstance(v, str):
                    return v.replace("{{refreshToken}}", refresh_token).replace("{{refresh_token}}", refresh_token)
                elif isinstance(v, dict):
                    return {k2: _sub(v2) for k2, v2 in v.items()}
                elif isinstance(v, list):
                    return [_sub(x) for x in v]
                return v
            body = _sub(dict(body))
            if "refresh_token" not in body and "refreshToken" not in body:
                body["refresh_token"] = refresh_token

        if method == "POST":
            if isinstance(body, dict):
                resp = await client.post(url, json=body, headers=headers, timeout=15.0)
            else:
                resp = await client.post(url, content=str(body), headers=headers, timeout=15.0)
        else:
            resp = await client.request(method, url, headers=headers, timeout=15.0)

        if resp.status_code >= 400:
            raise NodeExecutionError(
                f"Manual token refresh failed ({resp.status_code}): {resp.text[:200]}",
                code="AUTH_REFRESH_FAILED",
                node_id="token_manager",
                retryable=False,
            )

        resp_data = resp.json() if (resp.headers.get("content-type", "").startswith("application/json") or resp.text.startswith("{")) else {}
        extracted = _extract_from_item(resp_data)
        if not extracted.get("access_token"):
            raise NodeExecutionError(
                "Manual token refresh response did not contain an access_token.",
                code="AUTH_REFRESH_FAILED",
                node_id="token_manager",
                retryable=False,
            )
        if not extracted.get("refresh_token"):
            extracted["refresh_token"] = refresh_token

        raw_exp_at = extracted.get("expires_at")
        raw_exp_in = extracted.get("expires_in")
        epoch = normalize_expires_at(raw_exp_at)
        if epoch is None and raw_exp_in:
            try:
                epoch = time.time() + float(raw_exp_in)
            except (TypeError, ValueError):
                epoch = None
        extracted["expires_at"] = epoch
        for k in ("client_id", "client_secret", "token_url", "instance_url", "scope"):
            if bundle.get(k) and not extracted.get(k):
                extracted[k] = bundle[k]
        return extracted
    finally:
        if own_client:
            await client.aclose()


def _node_result(formatted: dict[str, Any] | list[dict[str, Any]], is_valid: bool) -> NodeResult:
    items = formatted if isinstance(formatted, list) else [formatted]
    return NodeResult(
        output_items=items,
        output_by_handle={
            "valid": items if is_valid else [],
            "login": items if not is_valid else [],
            "main": items,
        },
    )


@register
class TokenManagerNode(BaseNode[TokenManagerParams]):
    node_type = "token_manager"
    display_name = "Token Manager"
    version = 1
    description = "Universal token lifecycle manager: automatically fetches stored credentials, auto-refreshes expired tokens, and saves new logins to database."
    category = "Actions"
    icon = "token_manager"
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
            formatted = _format_outputs(
                input_items,
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

        base_in = input_items[0] if input_items else None

        # First run / No credentials exist in database -> Try auto-login on first run!
        if state is None:
            login_cfg = await _resolve_login_config(ctx, params, wf_id)
            if login_cfg and getattr(ctx, "http_client", None):
                logged_in = await _execute_login(
                    ctx, login_cfg, wf_id, provider, params, base_item=base_in,
                )
                if logged_in:
                    if input_items and len(input_items) > 1:
                        output_list = [
                            {**item, **{k: v for k, v in logged_in.items() if k not in ("id",)}}
                            for item in input_items
                        ]
                    else:
                        output_list = [logged_in]
                    return NodeResult(
                        output_items=output_list,
                        output_by_handle={
                            "valid": output_list,
                            "login": output_list,
                            "main": output_list,
                        },
                    )

            ctx.logger.info(
                "token manager: workflow=%s provider=%s status=MISSING (auth required)",
                wf_id, provider,
            )
            formatted = _format_outputs(
                input_items,
                wf_id, provider, None,
                status="MISSING", source="none", is_valid=False,
            )
            return _node_result(formatted, is_valid=False)

        epoch = normalize_expires_at(state.get("expires_at"))

        # Check if upstream node passed a 401 error or unauthorized response
        incoming_is_invalid = False
        if input_items:
            for item in input_items:
                if isinstance(item, dict):
                    sc = item.get("statusCode") or item.get("status") or item.get("status_code")
                    resp = item.get("response")
                    if isinstance(resp, dict):
                        sc = sc or resp.get("status_code") or resp.get("statusCode") or resp.get("status")

                    err_text = (
                        str(item.get("error") or "") + " " +
                        str(item.get("message") or "") + " " +
                        str(item.get("body") or "") + " " +
                        str(resp if isinstance(resp, (dict, str)) else "")
                    ).lower()
                    if sc in (401, 403) or any(
                        w in err_text for w in (
                            "unauthorized", "invalid_token", "token expired",
                            "expired_token", "invalid_grant", "session expired"
                        )
                    ):
                        incoming_is_invalid = True
                        break

        if params.refresh_token and params.refresh_token.strip():
            state["refresh_token"] = params.refresh_token.strip()

        token_is_expired = is_expired(epoch) or incoming_is_invalid or not bool(state.get("access_token"))

        # Stored credentials are still valid -> reuse them (unless force_refresh is enabled)! DO NOT call Login API!
        if not token_is_expired and not params.force_refresh:
            ctx.logger.info(
                "token manager: workflow=%s provider=%s status=VALID (reusing stored token, skipping login)",
                wf_id, provider,
            )
            formatted = _format_outputs(
                input_items,
                wf_id, provider, state,
                status="VALID", source="stored_credentials", is_valid=True,
            )
            return _node_result(formatted, is_valid=True)

        # Token is expired or invalid (or force_refresh is enabled) -> attempt automatic single-flight refresh
        attempts = 0
        last_error = ""
        while attempts < max(params.max_recovery_attempts, 1):
            if not params.auto_refresh and params.mode != "refresh" and not params.force_refresh:
                break
            if not str(state.get("refresh_token") or "").strip():
                last_error = "AUTH_REFRESH_FAILED"
                break
            attempts += 1
            db = get_session()
            try:
                async def _do_refresh(bundle: dict[str, Any], _provider: str = provider) -> dict[str, Any]:
                    custom_url = (params.refresh_url or "").strip()
                    if custom_url:
                        return await _execute_custom_refresh(ctx, params, bundle, custom_url)
                    return await refresh_bundle(_provider, bundle)

                try:
                    fresh = await locked_refresh(db, wf_id, provider, _do_refresh, force=params.force_refresh)
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
            if not is_expired(normalize_expires_at(state.get("expires_at"))) or params.force_refresh:
                ctx.logger.info(
                    "token manager: workflow=%s provider=%s status=REFRESHED (skipping login)",
                    wf_id, provider,
                )
                formatted = _format_outputs(
                    input_items,
                    wf_id, provider, state,
                    status="REFRESHED", source="refreshed", is_valid=True,
                )
                return _node_result(formatted, is_valid=True)
            last_error = "AUTH_REFRESH_FAILED"
            break

        # Refresh failed or refresh token missing -> attempt auto-login fallback before giving up (only in auto mode)
        if params.mode not in ("fetch", "refresh"):
            login_cfg = await _resolve_login_config(ctx, params, wf_id)
            if login_cfg and getattr(ctx, "http_client", None):
                logged_in = await _execute_login(
                    ctx, login_cfg, wf_id, provider, params, base_item=base_in,
                )
                if logged_in:
                    if input_items and len(input_items) > 1:
                        output_list = [
                            {**item, **{k: v for k, v in logged_in.items() if k not in ("id",)}}
                            for item in input_items
                        ]
                    else:
                        output_list = [logged_in]
                    return NodeResult(
                        output_items=output_list,
                        output_by_handle={
                            "valid": output_list,
                            "login": output_list,
                            "main": output_list,
                        },
                    )

        # Mark re-auth required
        db = get_session()
        try:
            mark_failed(db, wf_id, provider, last_error or "AUTH_REAUTH_REQUIRED")
        finally:
            db.close()

        ctx.logger.info(
            "token manager: workflow=%s provider=%s status=REAUTH_REQUIRED (routing to Login API)",
            wf_id, provider,
        )
        formatted = _format_outputs(
            input_items,
            wf_id, provider, state,
            status="REAUTH_REQUIRED", source="stored_credentials", is_valid=False,
        )
        return _node_result(formatted, is_valid=False)
