"""Password hashing (stdlib pbkdf2) and JWT issuing/verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings

logger = logging.getLogger(__name__)

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 600_000

# In-memory fallback for token blacklist when Redis is unavailable (bounded to prevent leaks)
_token_blacklist: dict[str, float] = {}
_MAX_BLACKLIST_SIZE = 10_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        iterations = int(iterations)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return hmac.compare_digest(digest, expected)


# Precomputed-format dummy hash: login runs this for missing/inactive
# accounts so a bad-password attempt always pays the full pbkdf2 cost
# (timing-based user enumeration defence).
DUMMY_PASSWORD_HASH = (
    f"{_ALGO}${_ITERATIONS}"
    f"${base64.b64encode(b'\x00' * 16).decode()}"
    f"${base64.b64encode(b'\x00' * 32).decode()}"
)


def _get_jwt_secret() -> str:
    """Return JWT secret, auto-generating a secure one if unconfigured.

    Covers both the shipped insecure default and an empty/blank value —
    compose passes ``JWT_SECRET: ${JWT_SECRET:-}``, so a missing server
    env var arrives as ``""``, which would otherwise be used as the
    signing key and allow token forgery.
    """
    settings = get_settings()
    if not (settings.jwt_secret or "").strip() or settings.jwt_secret == "dev-only-secret-change-me":
        # Auto-generate a cryptographically secure secret on first use
        generated = secrets.token_urlsafe(48)
        logger.warning(
            "JWT_SECRET not configured - auto-generated a secure key for this process. "
            "Set JWT_SECRET in your environment for persistent tokens across restarts."
        )
        # Patch the settings object so subsequent calls use the generated key
        settings.jwt_secret = generated
    return settings.jwt_secret


def _is_token_revoked(jti: str) -> bool:
    """Check if a token has been revoked (blacklisted)."""
    # Try Redis first for distributed blacklist
    try:
        from app.security.redis_client import get_shared_redis
        r = get_shared_redis()
        if r is not None:
            return r.get(f"token_revoked:{jti}") is not None
    except Exception:
        pass
    # Fallback to in-memory blacklist
    now_ts = datetime.now(UTC).timestamp()
    exp_ts = _token_blacklist.get(jti)
    if exp_ts is not None:
        if exp_ts > now_ts:
            return True
        _token_blacklist.pop(jti, None)
    return False


def create_token(user_id: int, email: str | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    jti = secrets.token_urlsafe(16)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
        "jti": jti,
    }
    if email:
        payload["email"] = email
    return jwt.encode(payload, _get_jwt_secret(), algorithm=settings.jwt_algorithm)  # type: ignore[possibly-unbound]


def create_mfa_challenge_token(
    user_id: int,
    *,
    remember_device: bool = False,
    auto_renew: bool = True,
) -> str:
    """Issue a short-lived token that may ONLY be exchanged at /auth/mfa/verify."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "purpose": "mfa",
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=5),
        "jti": secrets.token_urlsafe(16),
        "remember_device": bool(remember_device),
        "auto_renew": bool(auto_renew),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=settings.jwt_algorithm)  # type: ignore[possibly-unbound]


def create_mfa_enrollment_token(
    user_id: int,
    *,
    remember_device: bool = False,
    auto_renew: bool = True,
    method: str = "password",
) -> str:
    """Issue a 10-minute token that may ONLY enroll TOTP after a policy login."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "purpose": "mfa_enroll",
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=10),
        "jti": secrets.token_urlsafe(16),
        "remember_device": bool(remember_device),
        "auto_renew": bool(auto_renew),
        "method": method,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=settings.jwt_algorithm)  # type: ignore[possibly-unbound]


def decode_mfa_challenge_token(token: str) -> dict:
    data = decode_token(token, allow_purpose=True)
    if data.get("purpose") != "mfa":
        raise jwt.InvalidTokenError("Not an MFA challenge token.")
    return data


def decode_mfa_enrollment_token(token: str) -> dict:
    data = decode_token(token, allow_purpose=True)
    if data.get("purpose") != "mfa_enroll":
        raise jwt.InvalidTokenError("Not an MFA enrollment token.")
    return data


def create_webauthn_challenge_token(
    user_id: int,
    challenge: bytes,
    kind: str,
    *,
    remember_device: bool = False,
    auto_renew: bool = True,
    method: str = "password",
) -> str:
    if kind not in ("register", "authenticate"):
        raise ValueError("Invalid WebAuthn challenge kind.")
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "purpose": f"webauthn_{kind}",
        "challenge": base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("="),
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=5),
        "jti": secrets.token_urlsafe(16),
        "remember_device": bool(remember_device),
        "auto_renew": bool(auto_renew),
        "method": method,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=settings.jwt_algorithm)  # type: ignore[possibly-unbound]


def decode_webauthn_challenge_token(token: str, kind: str) -> dict:
    data = decode_token(token, allow_purpose=True)
    if data.get("purpose") != f"webauthn_{kind}":
        raise jwt.InvalidTokenError("Not a WebAuthn challenge token.")
    return data


def create_webauthn_conditional_token(challenge: bytes) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "purpose": "webauthn_conditional",
        "challenge": base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("="),
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=5),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=settings.jwt_algorithm)  # type: ignore[possibly-unbound]


def decode_webauthn_conditional_token(token: str) -> dict:
    data = decode_token(token, allow_purpose=True)
    if data.get("purpose") != "webauthn_conditional":
        raise jwt.InvalidTokenError("Not a conditional WebAuthn token.")
    return data


def decode_token(token: str, *, allow_purpose: bool = False) -> dict:
    """Raise jwt.InvalidTokenError on bad/expired/revoked/signed-with-other-secret tokens.

    Purpose-scoped tokens (currently MFA challenges) are rejected by default
    so every direct consumer - WebSockets, file downloads, session renewal,
    and bearer auth - treats them as non-credentials.
    """
    settings = get_settings()
    data = jwt.decode(token, _get_jwt_secret(), algorithms=[settings.jwt_algorithm])  # type: ignore[possibly-unbound]
    if data.get("purpose") and not allow_purpose:
        raise jwt.InvalidTokenError("Purpose-scoped token cannot be used as a credential.")
    # Check token revocation
    jti = data.get("jti")
    if jti and _is_token_revoked(jti):
        raise jwt.InvalidTokenError("Token has been revoked.")
    return data


def revoke_token(jti: str, exp: datetime | None = None) -> None:
    """Revoke a token by its jti claim. Stores in Redis with TTL if possible,
    otherwise in an in-memory set."""
    try:
        from app.security.redis_client import get_shared_redis
        r = get_shared_redis()
        if r is not None:
            # Set with TTL matching the token expiry
            ttl = 3600  # default 1 hour
            if exp:
                ttl = max(int((exp - datetime.now(UTC)).total_seconds()), 60)
            r.set(f"token_revoked:{jti}", "1", ex=ttl)
            return
    except Exception:
        pass
    # In-memory fallback: per-process only - other workers/API instances
    # will not see this revocation. Warn once so multi-worker deployments
    # notice the missing Redis.
    if not getattr(revoke_token, "_warned_fallback", False):
        revoke_token._warned_fallback = True  # type: ignore[attr-defined]
        logger.warning(
            "JWT revocation is using the in-memory fallback (Redis unavailable): "
            "revocations are per-process only and will not reach other workers."
        )
    now_ts = datetime.now(UTC).timestamp()
    expire_at = exp.timestamp() if exp else now_ts + 3600
    if len(_token_blacklist) >= _MAX_BLACKLIST_SIZE:
        expired_keys = [k for k, v in _token_blacklist.items() if v <= now_ts]
        for k in expired_keys:
            _token_blacklist.pop(k, None)
        if len(_token_blacklist) >= _MAX_BLACKLIST_SIZE:
            for k in list(_token_blacklist.keys())[:1000]:
                _token_blacklist.pop(k, None)
    _token_blacklist[jti] = expire_at


def get_worker_id() -> str:
    """Stable per-process identity used by queue workers (spec 34: claim
    ownership + heartbeats must be attributable to a worker)."""
    import socket

    return f"{socket.gethostname()}:{os.getpid()}"
