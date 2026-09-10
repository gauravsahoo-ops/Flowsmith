"""Provider refresh adapters — data, not branches.

Every OAuth2 provider refreshes through the shared `OAuthManager`
engine; this table only supplies each provider's token endpoint and
documents which providers are static (no refresh possible). Unknown
provider keys fall back to `oauth2` when the bundle carries its own
`token_url`, otherwise they fail fast with AUTH_PROVIDER_NOT_SUPPORTED.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from app.credentials.oauth_manager import OAuthManager
from app.engine.errors import NodeExecutionError

# provider -> {"token_url"} for refreshable, or {"static": True}.
PROVIDER_REFRESH: dict[str, dict[str, Any]] = {
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
    if not token_url or not client_id or not client_secret:
        raise NodeExecutionError(
            "Refresh needs token_url + client_id + client_secret in the stored bundle.",
            code="AUTH_REFRESH_FAILED", node_id="auth_fetch", retryable=False,
        )
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
    new_bundle["access_token"] = refreshed.get("access_token", bundle.get("access_token"))
    # Preserve the existing refresh token unless rotated.
    if refreshed.get("refresh_token"):
        new_bundle["refresh_token"] = refreshed["refresh_token"]
    if refreshed.get("expires_at"):
        try:
            new_bundle["expires_at"] = float(refreshed["expires_at"])
        except (TypeError, ValueError):
            pass
    elif refreshed.get("expires_in"):
        try:
            new_bundle["expires_at"] = time.time() + float(refreshed["expires_in"])
        except (TypeError, ValueError):
            pass
    new_bundle["token_url"] = token_url
    new_bundle["client_id"] = client_id
    return new_bundle
