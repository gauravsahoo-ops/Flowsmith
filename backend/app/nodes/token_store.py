"""Token Store node — persist workflow authentication credentials.

Receives tokens from Login API / HTTP Request / Token refresh step,
normalizes them, and safely performs an atomic encrypted UPSERT into the
credential store under (workflow_id, provider).

Supports 100% AUTOMATIC MODE:
If access_token or other fields are not manually mapped, it automatically
inspects the incoming data (body, JSON, or data) from the upstream node
and auto-extracts access_token, refresh_token, expires_in, expires_at, etc.
Zero manual mapping required.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.auth_state.adapter import canonical_provider, normalize_expires_at
from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class TokenStoreParams(BaseModel):
    provider: str = Field(
        default="salesforce",
        description="Provider or auth type, e.g. salesforce, google, shopify, github, slack, microsoft, custom.",
    )
    workflow_id: str = Field(
        default="",
        description="Optional workflow ID override. Defaults automatically to current execution workflow.",
    )
    auto_detect: bool = Field(
        default=True,
        description="Automatically extract access_token and refresh_token from upstream node output.",
    )
    access_token: str = Field(
        default="",
        description="Access token (leave empty for automatic detection from upstream node).",
    )
    refresh_token: str = Field(
        default="",
        description="Refresh token (leave empty for automatic detection).",
    )
    token_type: str = Field(
        default="Bearer",
        description="Token type, e.g. Bearer.",
    )
    scope: str = Field(
        default="",
        description="Granted scope string.",
    )
    expires_at: Any = Field(
        default=None,
        description="Expiration epoch seconds or ISO timestamp string.",
    )
    expires_in: float | None = Field(
        default=None,
        description="Seconds until token expiration (alternative to expires_at).",
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
    """Inspect upstream item and its nested body/json/data for OAuth tokens."""
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


@register
class TokenStoreNode(BaseNode[TokenStoreParams]):
    node_type = "token_store"
    display_name = "Token Store"
    version = 1
    description = "Securely save authentication credentials received from Login API / HTTP Request (encrypted UPSERT)."
    category = "Actions"
    icon = "token_store"
    parameters_schema = TokenStoreParams
    idempotency = "conditionally_idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: TokenStoreParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from app.auth_state.service import upsert_state
        from app.db import get_session

        wf_id = (params.workflow_id or ctx.workflow_id or "").strip()
        provider = canonical_provider(params.provider or "salesforce")
        if not provider:
            raise NodeExecutionError(
                "Token Store requires a valid provider name.",
                code="AUTH_PROVIDER_NOT_SUPPORTED",
                node_id=self.node_type,
                retryable=False,
            )

        # Automatic detection from upstream node output
        auto_data: dict[str, Any] = {}
        if input_items:
            auto_data = _extract_from_item(input_items[0])

        access_token = (params.access_token or "").strip()
        if not access_token and params.auto_detect and auto_data.get("access_token"):
            access_token = auto_data["access_token"]
            ctx.logger.info("token store: automatically extracted access_token from upstream node")

        if not access_token:
            raise NodeExecutionError(
                "Token Store could not find an access_token. Either provide an Access Token mapping or connect the Login API / HTTP Request output directly before this node.",
                code="AUTH_STORAGE_FAILED",
                node_id=self.node_type,
                retryable=False,
            )

        refresh_token = (params.refresh_token or "").strip()
        if not refresh_token and params.auto_detect and auto_data.get("refresh_token"):
            refresh_token = auto_data["refresh_token"]

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
                f"Token Store could not persist credentials: {exc}",
                code="AUTH_STORAGE_FAILED",
                node_id=self.node_type,
                retryable=True,
            ) from exc
        finally:
            db.close()

        ctx.logger.info(
            "token stored: workflow=%s provider=%s updated=%s auto_detected=%s",
            wf_id, provider, not created, bool(auto_data),
        )

        return NodeResult(
            output_items=[{
                "saved": True,
                "workflowId": wf_id,
                "provider": provider,
                "credentialId": row_id,
                "updated": not created,
                "accessToken": access_token,
                "refreshToken": refresh_token or None,
                "expiresAt": datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None,
                "tokenType": token_type,
                "scope": scope or None,
                "isValid": True,
                "source": "stored_credentials",
                "status": "STORED",
                "requiresAuthentication": False,
                "autoDetected": bool(auto_data),
            }]
        )
