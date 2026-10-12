"""Authentication Error Classification Service.

Maps provider error responses, status codes, and exception types to
precise recovery actions, preventing retry storms on permanent failures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.recovery_state import AuthErrorCode


class RecoveryAction:
    REFRESH = "REFRESH"
    RETRY_LATER = "RETRY_LATER"
    REQUIRE_REAUTHORIZATION = "REQUIRE_REAUTHORIZATION"
    MANUAL_ACTION_REQUIRED = "MANUAL_ACTION_REQUIRED"
    NOTIFY_ADMIN = "NOTIFY_ADMIN"
    STOP_RECOVERY = "STOP_RECOVERY"


@dataclass(frozen=True)
class ClassifiedAuthError:
    code: AuthErrorCode
    action: str
    message: str
    retryable: bool
    requires_user_action: bool
    retry_after_seconds: float | None = None


def classify_auth_error(
    error_data: Any,
    status_code: int | None = None,
    provider: str = "",
) -> ClassifiedAuthError:
    """Classify an authentication error and dictate recovery action."""
    raw_text = ""
    if isinstance(error_data, dict):
        raw_text = " ".join([
            str(error_data.get("error") or ""),
            str(error_data.get("error_description") or ""),
            str(error_data.get("message") or ""),
            str(error_data.get("code") or ""),
        ]).lower()
    else:
        raw_text = str(error_data or "").lower()

    # 1. Rate Limit / Throttle (429)
    if status_code == 429 or "rate_limit" in raw_text or "too many requests" in raw_text:
        retry_after = 60.0
        match = re.search(r"retry[-_]after[:\s]+(\d+)", raw_text)
        if match:
            try:
                retry_after = float(match.group(1))
            except Exception:
                pass
        return ClassifiedAuthError(
            code=AuthErrorCode.PROVIDER_RATE_LIMIT,
            action=RecoveryAction.RETRY_LATER,
            message="Provider rate limit reached. Backing off.",
            retryable=True,
            requires_user_action=False,
            retry_after_seconds=retry_after,
        )

    # 2. Temporary Network Failure / Provider Outage (502, 503, 504, connection errors)
    if status_code in (502, 503, 504) or any(
        term in raw_text for term in ("timeout", "connection refused", "connecterror", "service unavailable", "gateway timeout")
    ):
        return ClassifiedAuthError(
            code=AuthErrorCode.PROVIDER_UNAVAILABLE,
            action=RecoveryAction.RETRY_LATER,
            message="Provider endpoint temporarily unreachable.",
            retryable=True,
            requires_user_action=False,
            retry_after_seconds=30.0,
        )

    # 3. Refresh Token Revoked or Expired (invalid_grant, token revoked, consent required)
    if any(
        term in raw_text for term in (
            "invalid_grant",
            "refresh token expired",
            "refresh token has been revoked",
            "token has been revoked",
            "revoked_grant",
            "expired_grant",
            "user_revoked",
            "consent_required",
            "interaction_required",
        )
    ):
        return ClassifiedAuthError(
            code=AuthErrorCode.REFRESH_TOKEN_REVOKED,
            action=RecoveryAction.REQUIRE_REAUTHORIZATION,
            message="Refresh token has expired or was revoked by provider. User reauthorization required.",
            retryable=False,
            requires_user_action=True,
        )

    # 4. Access Token Expired (401 or token expired keywords without invalid_grant)
    if (
        status_code == 401
        or "token_expired" in raw_text
        or "expired_token" in raw_text
        or "session expired or invalid" in raw_text
        or "invalid_token" in raw_text
    ):
        return ClassifiedAuthError(
            code=AuthErrorCode.ACCESS_TOKEN_EXPIRED,
            action=RecoveryAction.REFRESH,
            message="Access token expired. Automatic refresh eligible.",
            retryable=True,
            requires_user_action=False,
        )

    # 5. Invalid Client Credentials (invalid_client, unauthorized_client)
    if any(
        term in raw_text for term in ("invalid_client", "unauthorized_client", "bad client credentials", "client secret expired")
    ):
        return ClassifiedAuthError(
            code=AuthErrorCode.INVALID_CLIENT_CREDENTIALS,
            action=RecoveryAction.MANUAL_ACTION_REQUIRED,
            message="Invalid or expired client application credentials. Contact administrator.",
            retryable=False,
            requires_user_action=True,
        )

    # 6. Insufficient Permissions / Scopes (403, missing scope)
    if status_code == 403 or "insufficient_scope" in raw_text or "access_denied" in raw_text:
        return ClassifiedAuthError(
            code=AuthErrorCode.INSUFFICIENT_PERMISSIONS,
            action=RecoveryAction.MANUAL_ACTION_REQUIRED,
            message="Insufficient permissions or scopes granted.",
            retryable=False,
            requires_user_action=True,
        )

    # 7. Invalid API Key
    if any(term in raw_text for term in ("invalid api key", "api_key_invalid", "unauthorized key")):
        return ClassifiedAuthError(
            code=AuthErrorCode.INVALID_API_KEY,
            action=RecoveryAction.MANUAL_ACTION_REQUIRED,
            message="Invalid API Key. Must be replaced manually.",
            retryable=False,
            requires_user_action=True,
        )

    # Default fallback
    return ClassifiedAuthError(
        code=AuthErrorCode.UNKNOWN,
        action=RecoveryAction.STOP_RECOVERY,
        message=f"Authentication error: {raw_text[:200]}",
        retryable=False,
        requires_user_action=True,
    )
