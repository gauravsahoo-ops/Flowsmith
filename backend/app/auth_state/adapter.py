"""Provider refresh adapters — data, not branches.

Every OAuth2 provider refreshes through the shared `OAuthManager`
engine; this table only supplies each provider's token endpoint and
documents which providers are static (no refresh possible). Unknown
provider keys fall back to `oauth2` when the bundle carries its own
`token_url`, otherwise they fail fast with AUTH_PROVIDER_NOT_SUPPORTED.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from app.credentials.oauth_manager import OAuthManager
from app.engine.errors import NodeExecutionError

# provider -> {"token_url"} for refreshable, or {"static": True}.
PROVIDER_REFRESH: dict[str, dict[str, Any]] = {
    "convertalogic": {"token_url": "https://convertalogic-dev.dev.idslogic.net/api/v1/auth/refresh", "json": True},
    "salesforce": {"token_url": "https://login.salesforce.com/services/oauth2/token"},
    "google": {"token_url": "https://oauth2.googleapis.com/token"},
    "hubspot": {"token_url": "https://api.hubapi.com/oauth/v1/token"},
    "microsoft": {"token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token"},
    "github": {"token_url": "https://github.com/login/oauth/access_token"},
    "slack": {"static": True},
    "shopify": {"static": True},
    "custom": {},
    "oauth2": {},
    "api_key": {"static": True},
    "bearer_token": {"static": True},
    "basic_auth": {"static": True},
}

# Aliases for connector-flavored provider keys.
PROVIDER_ALIASES: dict[str, str] = {
    "google_calendar": "google",
    "google_sheets": "google",
    "google_drive": "google",
    "google_docs": "google",
    "gmail": "google",
    "msteams": "microsoft",
    "outlook": "microsoft",
}


def canonical_provider(provider: str) -> str:
    key = (provider or "").strip().lower()
    return PROVIDER_ALIASES.get(key, key)


def normalize_expires_at(value: Any) -> float | None:
    """Accept epoch seconds, ISO strings, or {'expires_in': seconds}."""
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return normalize_expires_at(value.get("expires_at", value.get("expires_in")))
    if isinstance(value, (int, float)):
        return float(value) if float(value) > 0 else None
    text = str(value).strip()
    try:
        return float(text) if float(text) > 0 else None
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.timestamp()
    except ValueError:
        return None


def is_expired(expires_at: float | None, skew_s: float = 60.0) -> bool:
    if not expires_at:
        return False
    return time.time() >= (expires_at - skew_s)


def mask_token(token: str | None, prefix_len: int = 8, mask_len: int = 8) -> str:
    """Safely mask tokens for UI and logs (e.g. eyJhbGci...••••••••)."""
    if not token or not token.strip():
        return ""
    s = token.strip()
    if len(s) <= prefix_len:
        return "••••••••"
    return f"{s[:prefix_len]}...{'•' * mask_len}"


def normalize_token_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize varying token response payloads (camelCase / snake_case)."""
    if not isinstance(raw, dict):
        return {}
    access_token = raw.get("access_token") or raw.get("accessToken") or raw.get("token") or ""
    refresh_token = raw.get("refresh_token") or raw.get("refreshToken") or ""
    token_type = raw.get("token_type") or raw.get("tokenType") or "Bearer"
    scope = raw.get("scope") or raw.get("scopes") or ""
    expires_in = raw.get("expires_in") or raw.get("expiresIn")
    expires_at = raw.get("expires_at") or raw.get("expiresAt")
    epoch = normalize_expires_at(expires_at)
    if epoch is None and expires_in is not None:
        try:
            epoch = time.time() + float(expires_in)
        except (TypeError, ValueError):
            epoch = None
    return {
        "access_token": str(access_token) if access_token else "",
        "refresh_token": str(refresh_token) if refresh_token else None,
        "token_type": str(token_type) if token_type else "Bearer",
        "scope": str(scope) if scope else None,
        "expires_at": epoch,
    }


async def refresh_bundle(provider: str, bundle: dict[str, Any]) -> dict[str, Any]:
    """Refresh one stored bundle via the shared OAuth2 engine.

    Returns the NEW bundle (rotated refresh token preserved when the
    provider omits it). Raises NodeExecutionError with AUTH_* codes.
    """
    key = canonical_provider(provider)
    spec = PROVIDER_REFRESH.get(key)
    if spec is None:
        # Unknown provider: allow explicit bundles carrying token_url.
        if not bundle.get("token_url"):
            raise NodeExecutionError(
                f"Auth provider '{provider}' is not supported for refresh.",
                code="AUTH_PROVIDER_NOT_SUPPORTED", node_id="auth_fetch", retryable=False,
            )
        spec = {}
    if spec.get("static"):
        raise NodeExecutionError(
            f"Provider '{key}' uses non-refreshable tokens; reconnect required.",
            code="AUTH_REFRESH_FAILED", node_id="auth_fetch", retryable=False,
        )
    refresh_token = str(bundle.get("refresh_token") or "").strip()
    if not refresh_token:
        raise NodeExecutionError(
            "No refresh token stored; re-authentication required.",
            code="AUTH_REFRESH_FAILED", node_id="auth_fetch", retryable=False,
        )
    token_url = str(bundle.get("token_url") or spec.get("token_url") or "").strip()
    client_id = str(bundle.get("client_id") or "").strip()
    client_secret = str(bundle.get("client_secret") or "").strip()

    # Stored bundle URLs are attacker-influencable (token_store params):
    # refuse refresh against internal/loopback targets in production.
    if token_url:
        from app.security.ssrf import assert_public_url

        await assert_public_url(token_url, node_id="auth_fetch")

    if spec.get("json") or not (client_id and client_secret):
        if not token_url:
            raise NodeExecutionError(
                "Refresh needs token_url in the stored bundle.",
                code="AUTH_REFRESH_FAILED", node_id="auth_fetch", retryable=False,
            )
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                body_payload = {"refresh_token": refresh_token}
                if client_id:
                    body_payload["client_id"] = client_id
                if client_secret:
                    body_payload["client_secret"] = client_secret
                resp = await client.post(
                    token_url,
                    json=body_payload,
                    headers={"Accept": "application/json"},
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    raise NodeExecutionError(
                        f"Token refresh failed ({resp.status_code}): {resp.text[:200]}",
                        code="AUTH_REFRESH_FAILED", node_id="auth_fetch", retryable=False,
                    )
                refreshed = resp.json()
        except NodeExecutionError:
            raise
        except Exception as exc:
            raise NodeExecutionError(
                f"Token endpoint unreachable: {exc}",
                code="AUTH_REFRESH_FAILED", node_id="auth_fetch", retryable=True,
            ) from exc
    else:
        try:
            refreshed = await OAuthManager().refresh({
                "token_url": token_url,
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            })
        except ValueError as exc:
            raise NodeExecutionError(
                f"Token refresh failed: {exc}",
                code="AUTH_REFRESH_FAILED", node_id="auth_fetch", retryable=False,
            ) from exc
        except Exception as exc:
            raise NodeExecutionError(
                f"Token endpoint unreachable: {exc}",
                code="AUTH_REFRESH_FAILED", node_id="auth_fetch", retryable=True,
            ) from exc
    new_bundle = dict(bundle)
    # Support wrapped responses, e.g. {"body": {...}} or {"data": {...}}
    payload_dict = refreshed
    if isinstance(refreshed, dict):
        for nested in ("body", "data", "json", "response", "auth"):
            if isinstance(refreshed.get(nested), dict):
                payload_dict = refreshed[nested]
                break

    new_at = (
        payload_dict.get("access_token")
        or payload_dict.get("accessToken")
        or payload_dict.get("token")
        or (refreshed.get("access_token") if isinstance(refreshed, dict) else None)
    )
    if new_at:
        new_bundle["access_token"] = str(new_at)

    new_rt = (
        payload_dict.get("refresh_token")
        or payload_dict.get("refreshToken")
        or (refreshed.get("refresh_token") if isinstance(refreshed, dict) else None)
    )
    if new_rt:
        new_bundle["refresh_token"] = str(new_rt)

    new_tt = payload_dict.get("token_type") or payload_dict.get("tokenType")
    if new_tt:
        new_bundle["token_type"] = str(new_tt)

    new_iu = payload_dict.get("instance_url") or payload_dict.get("instanceUrl")
    if new_iu:
        new_bundle["instance_url"] = str(new_iu)

    raw_ea = payload_dict.get("expires_at") or payload_dict.get("expiresAt")
    raw_ei = payload_dict.get("expires_in") or payload_dict.get("expiresIn")
    if raw_ea:
        try:
            new_bundle["expires_at"] = float(raw_ea)
        except (TypeError, ValueError):
            pass
    elif raw_ei:
        try:
            new_bundle["expires_at"] = time.time() + float(raw_ei)
        except (TypeError, ValueError):
            pass

    new_bundle["token_url"] = token_url
    if client_id:
        new_bundle["client_id"] = client_id
    if client_secret:
        new_bundle["client_secret"] = client_secret
    return new_bundle
