"""Auth endpoints (spec 9): register, login, current-user dependency.

Security (next phase): failed logins are throttled per-email and
per-IP (429 with Retry-After), the first account becomes the admin,
and deactivated accounts cannot log in or use tokens.
"""

from __future__ import annotations

import re

import jwt as pyjwt
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import ok
from app.audit import LOGIN, LOGIN_FAILED, PASSWORD_RESET, PASSWORD_RESET_REQUESTED, REGISTER, log_event
from app.config import get_settings
from app.db import get_db
from app.metrics import ratelimit_rejected
from app.models import PasswordResetToken, User
from app.security.jwt import create_token, decode_token, hash_password, revoke_token, verify_password
from app.security.ratelimit import SlidingWindowLimiter, get_login_throttle

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

login_throttle = get_login_throttle()
# Rate limiters for register and forgot-password (S9)
_register_limiter = SlidingWindowLimiter(capacity=100, window_s=60)  # 100 per minute per IP
_forgot_password_limiter = SlidingWindowLimiter(capacity=20, window_s=60)  # 20 per minute per IP


class _StrippedBody(BaseModel):
    """Strip whitespace on identity fields BEFORE validation so autofill/
    copy-paste padding never changes the meaning of an email/password."""

    @model_validator(mode="before")
    @classmethod
    def _strip_identity_fields(cls, data: Any):
        if isinstance(data, dict):
            for key in ("email", "password"):
                if isinstance(data.get(key), str):
                    data[key] = data[key].strip()
        return data


class RegisterRequest(_StrippedBody):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(_StrippedBody):
    email: EmailStr
    password: str


def _validate_password_complexity(password: str) -> None:
    """Enforce password complexity from config settings (S8: password complexity)."""
    settings = get_settings()
    errors = []
    if settings.password_require_uppercase and not re.search(r"[A-Z]", password):
        errors.append("uppercase letter")
    if settings.password_require_lowercase and not re.search(r"[a-z]", password):
        errors.append("lowercase letter")
    if settings.password_require_number and not re.search(r"\d", password):
        errors.append("digit")
    if settings.password_require_symbol and not re.search(r"[!@#$%^&*()_+\-=\[\]{}|;':\",./<>?]", password):
        errors.append("symbol")
    if errors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Password must contain at least: {', '.join(errors)}.",
        )


def _auth_payload(user: User) -> dict:
    return {
        "token": create_token(user.id),
        "user": {"id": user.id, "email": user.email, "role": user.role},
    }


def _client_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _raise_locked(key: str) -> None:
    ratelimit_rejected.inc(("login",))
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many failed attempts; try again later.",
        headers={"Retry-After": str(login_throttle.retry_after(key))},
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    ip = _client_key(request)
    allowed, retry = _register_limiter.allow(f"reg:{ip}")
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many registration attempts.", headers={"Retry-After": str(retry)})
    _validate_password_complexity(body.password)
    existing = db.scalar(select(User).where(User.email == body.email.lower()))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    # Normalize inputs deterministically: stray whitespace (autofill,
    # copy-paste) must not silently change identity material. Email is
    # case-insensitive by convention (strip already applied in model).
    body.email = body.email.lower()
    is_first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role="admin" if is_first else "member",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, REGISTER, target_type="user", target_id=str(user.id), user_id=user.id)
    log_event(db, LOGIN, target_type="user", target_id=str(user.id), user_id=user.id)
    return ok(_auth_payload(user))




# ----------------------------------------------------------------------
# Self-service password reset (Phase 42)
# ----------------------------------------------------------------------

RESET_LINK_PATH = "/reset-password"


def _send_reset_email(to: str, link: str) -> bool:
    """Best-effort SMTP delivery; returns False when SMTP is unconfigured
    or delivery fails (dev mode surfaces the link in the response)."""
    import logging
    import smtplib
    from email.message import EmailMessage

    settings = get_settings()
    logger = logging.getLogger("auth.reset")
    if not settings.smtp_host or not settings.mail_from:
        logger.warning("password reset for %s: SMTP unconfigured; link: %s", to, link)
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = "Flowsmith password reset"
        msg["From"] = settings.mail_from
        msg["To"] = to
        msg.set_content(f"Reset your password within 30 minutes:\n\n{link}")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True
    except Exception as exc:  # pragma: no cover - depends on external MTA
        logger.error("reset email failed for %s: %s", to, exc)
        return False


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Always 200 (no account enumeration). Stores a hashed single-use
    token and emails the reset link; in non-production the link is also
    returned so local users can complete the flow without an MTA."""
    import hashlib
    import secrets
    from datetime import UTC, datetime, timedelta

    from app.config import get_settings

    ip = _client_key(request)
    allowed, retry = _forgot_password_limiter.allow(f"fp:{ip}")
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many reset requests.", headers={"Retry-After": str(retry)})

    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    dev_link = None
    if user is not None:
        raw_token = secrets.token_urlsafe(32)
        ttl = get_settings().password_reset_ttl_seconds
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
        ))
        db.commit()
        base = (get_settings().public_url or str(request.base_url)).rstrip("/")
        link = f"{base}{RESET_LINK_PATH}?token={raw_token}"
        sent = _send_reset_email(email, link)
        if not sent and get_settings().app_env != "production":
            dev_link = link
        log_event(db, PASSWORD_RESET_REQUESTED, target_type="user",
                  target_id=str(user.id), user_id=user.id)
    resp: dict[str, Any] = {"sent": True}
    if dev_link:
        resp["dev_reset_link"] = dev_link
    return ok(resp)


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Consume a single-use token and set the new password."""
    import hashlib
    import secrets
    from datetime import UTC, datetime

    new_password = body.new_password.strip()
    if len(new_password) < get_settings().password_min_length:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Password must be at least {get_settings().password_min_length} characters.")
    _validate_password_complexity(new_password)

    token_hash = hashlib.sha256(body.token.strip().encode()).hexdigest()
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    now = datetime.now(UTC)
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token.")

    user = db.get(User, row.user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token.")

    user.password_hash = hash_password(new_password)
    row.used_at = now
    # Bulk-revoke all other pending reset tokens for this user
    from sqlalchemy import update
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.id != row.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    db.commit()

    # Proving email ownership earns a clean slate on both throttle keys.
    login_throttle.clear(f"login:{user.email}")
    login_throttle.clear(f"login_ip:{_client_key(request)}")
    log_event(db, PASSWORD_RESET, target_type="user", target_id=str(user.id), user_id=user.id)
    return ok({"reset": True})

@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    # Same normalization as register (Phase 42): whitespace + casing must
    # never make a valid password "wrong".
    body.email = body.email.lower()
    email_key = f"login:{body.email.lower()}"
    ip_key = f"login_ip:{_client_key(request)}"
    if login_throttle.is_locked(email_key) or login_throttle.is_locked(ip_key):
        _raise_locked(email_key)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        login_throttle.record_failure(email_key)
        login_throttle.record_failure(ip_key)
        log_event(db, LOGIN_FAILED, target_type="user",
                  target_id=str(user.id) if user else "",
                  detail={"email": body.email.lower()})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    login_throttle.clear(email_key)
    login_throttle.clear(ip_key)
    log_event(db, LOGIN, target_type="user", target_id=str(user.id), user_id=user.id)
    return ok(_auth_payload(user))


@router.post("/logout")
def logout(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke the current token (S2: token revocation)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    try:
        payload = decode_token(authorization.removeprefix("Bearer ").strip())
        jti = payload.get("jti")
        if jti:
            exp_ts = payload.get("exp")
            from datetime import datetime, timezone
            exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc) if exp_ts else None
            revoke_token(jti, exp_dt)
    except Exception:
        pass  # Best-effort revocation
    return ok({"message": "Logged out."})


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: require a valid Bearer JWT and return the user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    try:
        payload = decode_token(authorization.removeprefix("Bearer ").strip())
        user_id = int(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    return user


@router.get("/me")
def get_me(user: User = Depends(get_current_user)) -> dict:
    """Return the authenticated user profile."""
    return ok({
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "active": user.active,
        "created_at": str(user.created_at) if hasattr(user, "created_at") else None,
    })