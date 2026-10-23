"""Auth endpoints (spec 9): register, login, current-user dependency.

Security (next phase): failed logins are throttled per-email and
per-IP (429 with Retry-After), the first account becomes the admin,
and deactivated accounts cannot log in or use tokens.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading

import jwt as pyjwt
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import ok
from app.audit import LOGIN, LOGIN_FAILED, PASSWORD_RESET, PASSWORD_RESET_REQUESTED, REGISTER, log_event
from app.config import get_settings
from app.db import get_db
from app.metrics import ratelimit_rejected
from app.models import PasswordResetToken, User
from app.security.client_ip import client_ip as _trusted_client_ip
from app.security.jwt import (
    DUMMY_PASSWORD_HASH,
    create_token,
    decode_token,
    hash_password,
    revoke_token,
    verify_password,
)
from app.security.ratelimit import SlidingWindowLimiter, get_login_throttle

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger("auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

login_throttle = get_login_throttle()
# Rate limiters for register and forgot-password (S9)
_register_limiter = SlidingWindowLimiter(capacity=100, window_s=60)  # 100 per minute per IP
_forgot_password_limiter = SlidingWindowLimiter(capacity=20, window_s=60)  # 20 per minute per IP

# Serializes the "is this the first account?" count+insert. PostgreSQL uses
# an advisory transaction lock so multiple API replicas cannot both bootstrap
# an admin; SQLite (development/tests) falls back to a process lock because
# SQLite deployments are single-process by design.
_REGISTRATION_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP_ADVISORY_KEY = 0x46534D54


class _StrippedBody(BaseModel):
    """Strip whitespace on identity fields BEFORE validation so autofill/
    copy-paste padding never changes the meaning of an email/password."""

    @model_validator(mode="before")
    @classmethod
    def _strip_identity_fields(cls, data: Any):
        if isinstance(data, dict):
            for key in ("email", "password", "invite_code", "bootstrap_token"):
                if isinstance(data.get(key), str):
                    data[key] = data[key].strip()
        return data


class RegisterRequest(_StrippedBody):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    invite_code: str | None = None
    bootstrap_token: str | None = None


class LoginRequest(_StrippedBody):
    email: EmailStr
    password: str
    remember_device: bool = False
    auto_renew: bool = True


class SessionSettingsRequest(BaseModel):
    auto_renew: bool | None = None
    remember_device: bool | None = None


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


def _auth_payload(
    user: User,
    db: Session | None = None,
    ip_address: str = "unknown",
    user_agent: str = "",
    remember_device: bool = False,
    auto_renew: bool = True,
) -> dict:
    token = create_token(user.id, email=user.email)
    session_id = None
    if db is not None:
        try:
            from app.security.session_manager import SessionManager

            session = SessionManager.create_session(
                db=db,
                user=user,
                token=token,
                ip_address=ip_address,
                user_agent=user_agent,
                auto_renew=auto_renew,
                remember_device=remember_device,
            )
            session_id = session.id
        except Exception:
            logger.exception("Failed to create AuthSession for user %s", user.email)
    payload = {
        "token": token,
        "user": {"id": user.id, "email": user.email, "role": user.role},
    }
    if session_id:
        payload["session_id"] = session_id
    return payload


def _client_key(request: Request) -> str:
    return _trusted_client_ip(request)


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
    # Normalize inputs deterministically: stray whitespace (autofill,
    # copy-paste) must not silently change identity material. Email is
    # case-insensitive by convention (strip already applied in model).
    body.email = body.email.lower()
    settings = get_settings()
    mode = (settings.registration_mode or "open").strip().lower()
    password_hash = hash_password(body.password)

    with _REGISTRATION_BOOTSTRAP_LOCK:
        try:
            # Hold the lock through commit: the count and insert must be one
            # atomic unit or two replicas can both see zero users and both
            # create an admin.
            if db.get_bind().dialect.name == "postgresql":
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": _BOOTSTRAP_ADVISORY_KEY},
                )

            existing = db.scalar(select(User).where(User.email == body.email))
            if existing:
                raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
            is_first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
            if is_first and settings.registration_bootstrap_token:
                supplied_bootstrap = body.bootstrap_token or ""
                if not supplied_bootstrap or not secrets.compare_digest(
                    supplied_bootstrap, settings.registration_bootstrap_token
                ):
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        "A valid REGISTRATION_BOOTSTRAP_TOKEN is required to create the first admin.",
                    )
            if not is_first:
                if mode == "closed":
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        "Self-service registration is disabled. Contact an administrator.",
                    )
                if mode == "invite":
                    expected = settings.registration_invite_code or ""
                    supplied = body.invite_code or ""
                    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
                        raise HTTPException(
                            status.HTTP_403_FORBIDDEN,
                            "A valid invitation code is required to register.",
                        )
            user = User(
                email=body.email,
                password_hash=password_hash,
                role="admin" if is_first else "member",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "An account with this email already exists."
            ) from exc
        except Exception:
            db.rollback()
            raise

    log_event(db, REGISTER, target_type="user", target_id=str(user.id), user_id=user.id)
    log_event(db, LOGIN, target_type="user", target_id=str(user.id), user_id=user.id)
    ua = request.headers.get("user-agent", "")
    return ok(_auth_payload(user, db=db, ip_address=ip, user_agent=ua))




# ----------------------------------------------------------------------
# Self-service password reset (Phase 42)
# ----------------------------------------------------------------------

RESET_LINK_PATH = "/reset-password"


def _send_reset_email(to: str, link: str) -> bool:
    """Best-effort SMTP delivery; returns False when SMTP is unconfigured
    or delivery fails (non-production logs the link for local dev)."""
    import smtplib
    from email.message import EmailMessage

    settings = get_settings()
    reset_logger = logging.getLogger("auth.reset")
    if not settings.smtp_host or not settings.mail_from:
        if settings.app_env == "development":
            reset_logger.warning("password reset for %s: SMTP unconfigured; dev link: %s", to, link)
        else:
            reset_logger.warning("password reset for %s: SMTP unconfigured; link suppressed", to)
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = "Flowsmith password reset"
        msg["From"] = settings.mail_from
        msg["To"] = to
        msg.set_content(f"Reset your password within 30 minutes:\n\n{link}")
        use_ssl = bool(settings.smtp_use_tls or settings.smtp_port == 465)
        if use_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_starttls and settings.smtp_port != 25:
                    # Fail fast: never fall back to cleartext AUTH after a
                    # failed/unsupported STARTTLS negotiation.
                    server.starttls()
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        return True
    except Exception as exc:  # pragma: no cover - depends on external MTA
        reset_logger.error("reset email failed for %s: %s", to, exc)
        return False


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Always 200 (no account enumeration). Stores a hashed single-use
    token and emails the reset link; the link is never returned in the
    response."""
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
    if user is not None:
        raw_token = secrets.token_urlsafe(32)
        ttl = get_settings().password_reset_ttl_seconds
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
        ))
        db.commit()
        # Never build the reset link from an attacker-controllable Host header:
        # prefer the configured PUBLIC_URL; only in development fall back to
        # the request host. Otherwise suppress the mail (token would be wasted).
        _settings = get_settings()
        if _settings.public_url.strip():
            base = _settings.public_url.strip().rstrip("/")
        elif _settings.app_env == "development":
            base = str(request.base_url).rstrip("/")
        else:
            logger.error(
                "password reset suppressed for %s: PUBLIC_URL is not configured "
                "(reset links must not be derived from the Host header)", email
            )
            return ok({"sent": True})  # same shape: no user enumeration
        link = f"{base}{RESET_LINK_PATH}?token={raw_token}"
        sent = _send_reset_email(email, link)
        if not sent:
            logger.warning("password reset email not delivered for %s", email)
        log_event(db, PASSWORD_RESET_REQUESTED, target_type="user",
                  target_id=str(user.id), user_id=user.id)
    return ok({"sent": True})


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Consume a single-use token and set the new password."""
    import hashlib
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
    # Kill every outstanding bearer token (password resets assume compromise).
    from datetime import timezone as _tz
    user.tokens_valid_from = now if now.tzinfo else now.replace(tzinfo=_tz.utc)
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
    valid = False
    if user is not None and user.active:
        valid = verify_password(body.password, user.password_hash)
    else:
        # Constant-work path: missing/inactive accounts must cost the same
        # as a wrong password (timing-based user enumeration defence).
        verify_password(body.password, DUMMY_PASSWORD_HASH)
    if user is None or not user.active or not valid:
        login_throttle.record_failure(email_key)
        login_throttle.record_failure(ip_key)
        log_event(db, LOGIN_FAILED, target_type="user",
                  target_id=str(user.id) if user else "",
                  detail={"email": body.email.lower()})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    login_throttle.clear(email_key)
    login_throttle.clear(ip_key)
    log_event(db, LOGIN, target_type="user", target_id=str(user.id), user_id=user.id)
    ip = _client_key(request)
    ua = request.headers.get("user-agent", "")
    return ok(_auth_payload(
        user,
        db=db,
        ip_address=ip,
        user_agent=ua,
        remember_device=body.remember_device,
        auto_renew=body.auto_renew,
    ))


@router.post("/logout")
def logout(
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke the current token and invalidate its AuthSession."""
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    if not header_val or not header_val.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    try:
        payload = decode_token(header_val.removeprefix("Bearer ").strip())
        jti = payload.get("jti")
        if jti:
            exp_ts = payload.get("exp")
            from datetime import datetime, timezone
            exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc) if exp_ts else None
            revoke_token(jti, exp_dt)
            # Invalidate session in DB
            from app.models.auth_session import AuthSession
            now = datetime.now(timezone.utc)
            session = db.scalar(select(AuthSession).where(AuthSession.token_jti == jti))
            if session:
                session.is_active = False
                session.revoked_at = now
                db.commit()
    except Exception:
        pass  # Best-effort revocation
    return ok({"message": "Logged out."})


def token_is_stale(payload: dict, user: User) -> bool:
    """True when the token was issued before the user's tokens_valid_from cutoff."""
    valid_from = getattr(user, "tokens_valid_from", None)
    if valid_from is None:
        return False
    iat = payload.get("iat")
    if not isinstance(iat, int):
        return True  # untrusted freshness claim
    if valid_from.tzinfo is None:
        from datetime import timezone as _tz
        valid_from = valid_from.replace(tzinfo=_tz.utc)
    return iat < int(valid_from.timestamp())


def authenticate_token(token_str: str, db: Session) -> User:
    try:
        payload = decode_token(token_str)
        user_id = int(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    if token_is_stale(payload, user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please log in again.")
    return user


def get_current_user(
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: require a valid Bearer JWT and return the user."""
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    if not header_val or not header_val.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    return authenticate_token(header_val.removeprefix("Bearer ").strip(), db)


def get_metrics_user(
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Authentication for /api/metrics: Bearer header only."""
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    if not header_val or not header_val.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    return authenticate_token(header_val.removeprefix("Bearer ").strip(), db)


@router.get("/sessions")
def list_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """List all active Flowsmith login sessions for the current user."""
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    current_jti = None
    if header_val and header_val.startswith("Bearer "):
        try:
            payload = decode_token(header_val.removeprefix("Bearer ").strip())
            current_jti = payload.get("jti")
        except Exception:
            pass
    from app.security.session_manager import SessionManager

    sessions = SessionManager.list_user_sessions(db, user.id, current_jti=current_jti)
    return ok({"sessions": sessions})


@router.post("/sessions/renew")
def renew_session(
    request: Request,
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Renew the current application session using sliding expiration."""
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    if not header_val or not header_val.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    token_str = header_val.removeprefix("Bearer ").strip()
    from app.security.session_manager import SessionManager

    ip = _client_key(request)
    ua = request.headers.get("user-agent", "")
    try:
        res = SessionManager.renew_session(db, token_str, ip_address=ip, user_agent=ua)
        return ok(res)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))


@router.post("/sessions/{session_id}/revoke")
def revoke_single_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke a specific active session."""
    from app.security.session_manager import SessionManager

    success = SessionManager.revoke_session(db, user.id, session_id)
    if not success:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found.")
    return ok({"revoked": True, "session_id": session_id})


@router.post("/sessions/revoke-all")
def revoke_all_user_sessions(
    user: User = Depends(get_current_user),
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke all sessions for this user, sparing the current session."""
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    current_jti = None
    if header_val and header_val.startswith("Bearer "):
        try:
            payload = decode_token(header_val.removeprefix("Bearer ").strip())
            current_jti = payload.get("jti")
        except Exception:
            pass
    from app.security.session_manager import SessionManager

    count = SessionManager.revoke_all_sessions(db, user.id, except_jti=current_jti)
    return ok({"revoked_count": count})


@router.get("/sessions/settings")
def get_user_session_settings(
    user: User = Depends(get_current_user),
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Get active session preferences for the current device and user."""
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    current_jti = None
    if header_val and header_val.startswith("Bearer "):
        try:
            payload = decode_token(header_val.removeprefix("Bearer ").strip())
            current_jti = payload.get("jti")
        except Exception:
            pass
    from app.models.auth_session import AuthSession

    session = None
    if current_jti:
        session = db.scalar(select(AuthSession).where(AuthSession.token_jti == current_jti, AuthSession.user_id == user.id))
    return ok({
        "auto_renew": session.auto_renew if session else True,
        "remember_device": session.remember_device if session else False,
        "idle_timeout_minutes": session.idle_timeout_minutes if session else 1440,
        "max_lifetime_minutes": session.max_lifetime_minutes if session else 10080,
    })


@router.put("/sessions/settings")
def update_user_session_settings(
    body: SessionSettingsRequest,
    user: User = Depends(get_current_user),
    authorization: str | None = Header(default=None),
    x_authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Update auto_renew and remember_device preferences."""
    header_val = authorization if (authorization and authorization.startswith("Bearer ")) else x_authorization
    current_jti = None
    if header_val and header_val.startswith("Bearer "):
        try:
            payload = decode_token(header_val.removeprefix("Bearer ").strip())
            current_jti = payload.get("jti")
        except Exception:
            pass
    from app.security.session_manager import SessionManager

    res = SessionManager.update_session_settings(
        db,
        user_id=user.id,
        auto_renew=body.auto_renew,
        remember_device=body.remember_device,
        current_jti=current_jti,
    )
    return ok(res)


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


@router.post("/ws-ticket")
def post_ws_ticket(user: User = Depends(get_current_user)) -> dict:
    """One-time, short-TTL ticket for the WebSocket handshake.

    Lets the live-execution socket authenticate via ?ticket= instead of
    the raw bearer token (?token= leaked JWTs into logs/proxies).
    """
    from app.security.ws_ticket import WS_TICKET_TTL_S, issue_ws_ticket

    return ok({"ticket": issue_ws_ticket(user.id), "expires_in": WS_TICKET_TTL_S})
