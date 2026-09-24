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


def _get_jwt_secret() -> str:
    """Return JWT secret, auto-generating a secure one if the insecure default is used."""
    settings = get_settings()
    if settings.jwt_secret == "dev-only-secret-change-me":
        # Auto-generate a cryptographically secure secret on first use
        generated = secrets.token_urlsafe(48)
        logger.warning(
            "JWT_SECRET not configured — auto-generated a secure key for this process. "
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


def decode_token(token: str) -> dict:
    """Raise jwt.InvalidTokenError on bad/expired/revoked/signed-with-other-secret tokens."""
    settings = get_settings()
    data = jwt.decode(token, _get_jwt_secret(), algorithms=[settings.jwt_algorithm])  # type: ignore[possibly-unbound]
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
