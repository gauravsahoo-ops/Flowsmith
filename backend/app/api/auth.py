"""Auth endpoints (spec 9): register, login, current-user dependency.

Security (next phase): failed logins are throttled per-email and
per-IP (429 with Retry-After), the first account becomes the admin,
and deactivated accounts cannot log in or use tokens.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import threading
from datetime import UTC, datetime

import jwt as pyjwt
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import ok
from app.audit import (
    LOGIN,
    LOGIN_FAILED,
    MFA_CHALLENGE,
    MFA_DISABLED,
    MFA_ENABLED,
    MFA_ENROLLMENT_REQUIRED,
    MFA_ENROLLMENT_STARTED,
    MFA_VERIFIED,
    PASSKEY_ADDED,
    PASSKEY_REMOVED,
    PASSWORD_RESET,
    PASSWORD_RESET_REQUESTED,
    REGISTER,
    USER_ROLE_CHANGE,
    log_event,
)
from app.config import get_settings
from app.db import get_db
from app.metrics import ratelimit_rejected
from app.models import (
    Organization,
    OrganizationMember,
    PasswordResetToken,
    User,
    WebAuthnCredential,
    Workspace,
)
from app.security.client_ip import client_ip as _trusted_client_ip
from app.security.crypto import CredentialDecryptionError, decrypt_text, encrypt_text
from app.security.jwt import (
    DUMMY_PASSWORD_HASH,
    create_mfa_challenge_token,
    create_mfa_enrollment_token,
    create_token,
    create_webauthn_challenge_token,
    create_webauthn_conditional_token,
    decode_mfa_challenge_token,
    decode_mfa_enrollment_token,
    decode_token,
    decode_webauthn_challenge_token,
    decode_webauthn_conditional_token,
    hash_password,
    revoke_token,
    verify_password,
)
from app.security.ratelimit import SlidingWindowLimiter, get_login_throttle
from app.security.totp import generate_secret, provisioning_uri, verify_code
from app.services.ldap_auth import (
    LdapProfile,
    LdapUnavailable,
    authenticate_ldap,
    parse_group_role_map,
    role_for_groups,
)
from app.services.ldap_org_access import sync_ldap_organization_access
from app.services.ldap_workspace_access import sync_ldap_workspace_access
from app.services.user_provisioning import apply_default_scope
from app.services.webauthn import (
    WebAuthnConfigError,
    WebAuthnPolicyError,
    authentication_options,
    b64url,
    registration_options,
    require_webauthn_config,
    unb64url,
    verify_authentication,
    verify_registration,
)

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
    # Accepts an email address or an LDAP username (e.g. sAMAccountName/uid);
    # registration and password-reset still require a real email address.
    email: str = Field(min_length=1, max_length=255)
    password: str
    remember_device: bool = False
    auto_renew: bool = True


class SessionSettingsRequest(BaseModel):
    auto_renew: bool | None = None
    remember_device: bool | None = None


class MfaSetupRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class MfaEnableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=32)


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=32)


class MfaVerifyRequest(BaseModel):
    challenge_token: str = Field(min_length=1, max_length=4096)
    code: str = Field(min_length=1, max_length=32)


class MfaEnrollmentStartRequest(BaseModel):
    enrollment_token: str = Field(min_length=1, max_length=4096)


class MfaEnrollmentCompleteRequest(BaseModel):
    enrollment_token: str = Field(min_length=1, max_length=4096)
    code: str = Field(min_length=1, max_length=32)


class WebAuthnRegisterOptionsRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class WebAuthnRegisterCompleteRequest(BaseModel):
    registration_token: str = Field(min_length=1, max_length=4096)
    credential: dict[str, Any]
    name: str | None = Field(default=None, max_length=80)


class WebAuthnAuthenticateCompleteRequest(BaseModel):
    webauthn_token: str = Field(min_length=1, max_length=4096)
    credential: dict[str, Any]


MFA_ISSUER = "Flowsmith"
MFA_CHALLENGE_TTL_SECONDS = 300
MFA_ENROLLMENT_TTL_SECONDS = 600
MFA_RECOVERY_CODE_COUNT = 10
WEBAUTHN_CHALLENGE_TTL_SECONDS = 300


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


def _verify_mfa_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid password.")


def _mfa_secret(user: User) -> str:
    if not user.mfa_secret:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Multi-factor authentication is not configured.",
        )
    try:
        return decrypt_text(user.mfa_secret)
    except CredentialDecryptionError as exc:
        logger.exception("Stored MFA secret could not be decrypted for user %s", user.id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Multi-factor authentication is temporarily unavailable.",
        ) from exc


def _mfa_step(user: User, code: str) -> int:
    step = verify_code(_mfa_secret(user), code)
    if step is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Invalid authenticator code.",
        )
    if user.mfa_last_step is not None and step <= user.mfa_last_step:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That authenticator code was already used. Wait for the next code.",
        )
    return step


def _recovery_digest(code: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", code.upper())
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def _new_recovery_codes(user: User) -> list[str]:
    codes: list[str] = []
    for _ in range(MFA_RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(8).upper()
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:]}")
    user.mfa_recovery_hashes = json.dumps([_recovery_digest(code) for code in codes])
    return codes


def _consume_recovery_code(user: User, code: str) -> bool:
    if not user.mfa_recovery_hashes:
        return False
    try:
        hashes = json.loads(user.mfa_recovery_hashes)
    except (TypeError, ValueError):
        logger.warning("Invalid recovery-code state for user %s", user.id)
        return False
    if not isinstance(hashes, list):
        return False
    digest = _recovery_digest(code)
    if digest not in hashes:
        return False
    hashes.remove(digest)
    user.mfa_recovery_hashes = json.dumps(hashes)
    return True


def _ldap_role(profile: LdapProfile) -> str:
    settings = get_settings()
    return role_for_groups(
        profile.groups,
        parse_group_role_map(),
        settings.ldap_default_role,
    )


def _provision_ldap_user(db: Session, profile: LdapProfile) -> User | None:
    """Link or JIT-provision an LDAP user, applying mapped admin role.

    Existing administrators are never silently demoted by a missing LDAP
    group; promotion to admin is applied immediately.
    """
    settings = get_settings()
    email = profile.email.strip().lower()
    if "@" not in email or len(email) > 255:
        logger.warning("LDAP user %r has an unusable email address", profile.username)
        return None
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    desired_role = _ldap_role(profile)
    if user is None:
        if not settings.ldap_jit_provisioning:
            logger.info("LDAP user %r is not provisioned and JIT is disabled", profile.username)
            return None
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=desired_role,
            ldap_dn=profile.dn,
            ldap_groups=json.dumps(list(profile.groups)),
            ldap_synced_at=datetime.now(UTC),
        )
        db.add(user)
        try:
            db.flush()
            apply_default_scope(
                db,
                user,
                settings.ldap_default_organization_id,
                settings.ldap_default_workspace_id,
            )
            db.commit()
            db.refresh(user)
        except IntegrityError:
            # Two simultaneous first logins can both try to JIT the same user.
            db.rollback()
            user = db.scalar(select(User).where(func.lower(User.email) == email))
            if user is None or not user.active:
                return None
        except ValueError as exc:
            db.rollback()
            logger.error("LDAP default scope is invalid: %s", exc)
            return None
        log_event(db, REGISTER, target_type="user", target_id=str(user.id), user_id=user.id)
        _sync_ldap_access(db, user, profile.groups)
        return user
    if not user.active:
        return None
    user.ldap_dn = profile.dn
    user.ldap_groups = json.dumps(list(profile.groups))
    user.ldap_synced_at = datetime.now(UTC)
    if desired_role == "admin" and user.role != "admin":
        previous_role = user.role
        user.role = "admin"
        db.commit()
        log_event(
            db,
            USER_ROLE_CHANGE,
            target_type="user",
            target_id=str(user.id),
            user_id=user.id,
            detail={"from": previous_role, "to": "admin", "source": "ldap"},
        )
    else:
        db.commit()
    _sync_ldap_access(db, user, profile.groups)
    return user


def _sync_ldap_access(db: Session, user: User, groups: tuple[str, ...]) -> None:
    try:
        sync_ldap_workspace_access(db, user, groups)
        sync_ldap_organization_access(db, user, groups)
    except Exception:
        db.rollback()
        logger.exception("LDAP access synchronization failed for user %s", user.id)


def _try_ldap_login(identifier: str, password: str, db: Session) -> User | None:
    if not get_settings().ldap_enabled:
        return None
    try:
        profile = authenticate_ldap(identifier, password)
    except LdapUnavailable as exc:
        logger.warning("LDAP authentication unavailable: %s", exc)
        return None
    if profile is None:
        return None
    return _provision_ldap_user(db, profile)


def _webauthn_credentials(db: Session, user: User) -> list[WebAuthnCredential]:
    return list(
        db.execute(
            select(WebAuthnCredential)
            .where(WebAuthnCredential.user_id == user.id)
            .order_by(WebAuthnCredential.id)
        ).scalars().all()
    )


def _revoke_webauthn_challenge(payload: dict) -> None:
    jti = payload.get("jti")
    if not jti:
        return
    exp = payload.get("exp")
    expires_at = (
        datetime.fromtimestamp(int(exp), tz=UTC) if isinstance(exp, (int, float)) else None
    )
    revoke_token(str(jti), expires_at)


def _organization_requires_mfa(db: Session, user: User) -> bool:
    organization_id = user.organization_id
    if not organization_id and user.workspace_id:
        workspace = db.get(Workspace, user.workspace_id)
        organization_id = workspace.organization_id if workspace else None
    if organization_id:
        organization = db.get(Organization, organization_id)
        if organization is not None and organization.require_mfa:
            return True
    # Users may be organization members without the legacy primary
    # organization_id field being populated. Enforce the strictest policy
    # across all organizations they belong to.
    return db.scalar(
        select(OrganizationMember.id)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(
            OrganizationMember.user_id == user.id,
            Organization.require_mfa.is_(True),
        )
        .limit(1)
    ) is not None


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


@router.get("/mfa")
def mfa_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    credentials = _webauthn_credentials(db, user)
    return ok({
        "enabled": bool(user.mfa_enabled),
        "configured": bool(user.mfa_secret),
        "issuer": MFA_ISSUER,
        "webauthn_enabled": bool(get_settings().webauthn_enabled),
        "passkey_count": len(credentials),
    })


@router.post("/mfa/setup")
def mfa_setup(
    body: MfaSetupRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Generate a new TOTP secret; enrollment is completed by /mfa/enable."""
    if user.mfa_enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Multi-factor authentication is already enabled.",
        )
    _verify_mfa_password(user, body.password)
    secret = generate_secret()
    user.mfa_secret = encrypt_text(secret).decode("ascii")
    user.mfa_last_step = None
    user.mfa_recovery_hashes = None
    db.commit()
    return ok({
        "secret": secret,
        "otpauth_uri": provisioning_uri(secret, user.email, MFA_ISSUER),
        "issuer": MFA_ISSUER,
        "digits": 6,
        "period": 30,
    })


@router.post("/mfa/enable")
def mfa_enable(
    body: MfaEnableRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.mfa_enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Multi-factor authentication is already enabled.",
        )
    _verify_mfa_password(user, body.password)
    # Validate possession, but do not consume the enrollment code: the user
    # commonly signs in with the same current code immediately afterwards.
    _mfa_step(user, body.code)
    user.mfa_enabled = True
    user.mfa_last_step = None
    recovery_codes = _new_recovery_codes(user)
    db.commit()
    log_event(
        db, MFA_ENABLED,
        target_type="user", target_id=str(user.id), user_id=user.id,
    )
    return ok({"enabled": True, "recovery_codes": recovery_codes})


@router.post("/mfa/disable")
def mfa_disable(
    body: MfaDisableRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not user.mfa_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Multi-factor authentication is not enabled.",
        )
    if _organization_requires_mfa(db, user) and not _webauthn_credentials(db, user):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Your organization requires MFA; an organization founder must change the policy first.",
        )
    _verify_mfa_password(user, body.password)
    try:
        _mfa_step(user, body.code)
    except HTTPException:
        if not _consume_recovery_code(user, body.code):
            raise
    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_last_step = None
    user.mfa_recovery_hashes = None
    db.commit()
    log_event(
        db, MFA_DISABLED,
        target_type="user", target_id=str(user.id), user_id=user.id,
    )
    return ok({"enabled": False})


@router.post("/mfa/verify")
def mfa_verify(
    body: MfaVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Exchange a short-lived MFA challenge plus a TOTP code for a real token.

    The challenge token is deliberately not a bearer token: authenticate_token
    rejects any JWT carrying a ``purpose`` claim.
    """
    try:
        payload = decode_mfa_challenge_token(body.challenge_token.strip())
        user_id = int(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "MFA challenge expired or invalid. Sign in again.",
        )

    ip = _client_key(request)
    throttle_key = f"mfa:{user_id}:{ip}"
    if login_throttle.is_locked(throttle_key):
        _raise_locked(throttle_key)

    user = db.get(User, user_id)
    if user is None or not user.active or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA is not available for this account.")
    if token_is_stale(payload, user):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "MFA challenge expired. Sign in again.",
        )
    method = "totp"
    try:
        step = _mfa_step(user, body.code)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST and _consume_recovery_code(
            user, body.code
        ):
            step = None
            method = "recovery"
        else:
            login_throttle.record_failure(throttle_key)
            if exc.status_code == status.HTTP_400_BAD_REQUEST:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.detail) from exc
            raise
    if step is not None:
        user.mfa_last_step = step
    db.commit()
    login_throttle.clear(throttle_key)
    log_event(
        db, MFA_VERIFIED,
        target_type="user", target_id=str(user.id), user_id=user.id,
        detail={"method": method},
    )
    log_event(db, LOGIN, target_type="user", target_id=str(user.id), user_id=user.id)
    return ok(_auth_payload(
        user,
        db=db,
        ip_address=ip,
        user_agent=request.headers.get("user-agent", ""),
        remember_device=bool(payload.get("remember_device", False)),
        auto_renew=bool(payload.get("auto_renew", True)),
    ))


def _enrollment_user(db: Session, enrollment_token: str) -> tuple[dict, User]:
    try:
        payload = decode_mfa_enrollment_token(enrollment_token.strip())
        user_id = int(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "MFA enrollment expired or invalid. Sign in again.",
        )
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA enrollment is not available.")
    if token_is_stale(payload, user):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "MFA enrollment expired. Sign in again.",
        )
    if user.mfa_enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Multi-factor authentication is already enabled.",
        )
    return payload, user


@router.post("/mfa/enroll/start")
def mfa_enrollment_start(
    body: MfaEnrollmentStartRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Start forced MFA enrollment using the short-lived post-password token."""
    _, user = _enrollment_user(db, body.enrollment_token)
    secret = generate_secret()
    user.mfa_secret = encrypt_text(secret).decode("ascii")
    user.mfa_last_step = None
    user.mfa_recovery_hashes = None
    db.commit()
    log_event(
        db,
        MFA_ENROLLMENT_STARTED,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
    )
    return ok({
        "secret": secret,
        "otpauth_uri": provisioning_uri(secret, user.email, MFA_ISSUER),
        "issuer": MFA_ISSUER,
        "digits": 6,
        "period": 30,
    })


@router.post("/mfa/enroll/complete")
def mfa_enrollment_complete(
    body: MfaEnrollmentCompleteRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Verify the first code and immediately issue the normal login token."""
    payload, user = _enrollment_user(db, body.enrollment_token)
    ip = _client_key(request)
    throttle_key = f"mfa_enroll:{user.id}:{ip}"
    if login_throttle.is_locked(throttle_key):
        _raise_locked(throttle_key)
    try:
        _mfa_step(user, body.code)
    except HTTPException as exc:
        login_throttle.record_failure(throttle_key)
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.detail) from exc
        raise
    login_throttle.clear(throttle_key)
    user.mfa_enabled = True
    # The enrollment code is not consumed; the user may use the same current
    # code for an immediate second sign-in, while subsequent replays are
    # rejected by mfa_last_step once a challenge is completed.
    user.mfa_last_step = None
    recovery_codes = _new_recovery_codes(user)
    db.commit()
    log_event(
        db,
        MFA_ENABLED,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"source": "policy_enrollment"},
    )
    log_event(
        db,
        LOGIN,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"method": payload.get("method") or "password", "mfa": "enrolled"},
    )
    result = _auth_payload(
        user,
        db=db,
        ip_address=ip,
        user_agent=request.headers.get("user-agent", ""),
        remember_device=bool(payload.get("remember_device", False)),
        auto_renew=bool(payload.get("auto_renew", True)),
    )
    result["recovery_codes"] = recovery_codes
    return ok(result)


def _webauthn_user(db: Session, token: str, kind: str) -> tuple[dict, User]:
    try:
        payload = decode_webauthn_challenge_token(token.strip(), kind)
        user_id = int(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Passkey challenge expired or invalid. Sign in again.",
        )
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Passkey is not available for this account.")
    if token_is_stale(payload, user):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Passkey challenge expired. Sign in again.",
        )
    return payload, user


def _credential_id_from_body(credential: dict[str, Any]) -> bytes:
    raw = credential.get("rawId") or credential.get("id")
    if not isinstance(raw, str) or not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid passkey credential.")
    try:
        return unb64url(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid passkey credential.") from exc


@router.get("/webauthn")
def webauthn_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    credentials = _webauthn_credentials(db, user)
    return ok({
        "enabled": bool(get_settings().webauthn_enabled),
        "credentials": [
            {
                "id": b64url(credential.credential_id),
                "name": credential.name,
                "created_at": credential.created_at.isoformat() if credential.created_at else None,
                "last_used_at": credential.last_used_at.isoformat() if credential.last_used_at else None,
                "backed_up": bool(credential.backed_up),
            }
            for credential in credentials
        ],
    })


@router.post("/webauthn/register/options")
def webauthn_register_options(
    body: WebAuthnRegisterOptionsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        require_webauthn_config()
    except WebAuthnConfigError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _verify_mfa_password(user, body.password)
    credentials = _webauthn_credentials(db, user)
    options, challenge = registration_options(user, credentials)
    token = create_webauthn_challenge_token(user.id, challenge, "register")
    return ok({
        "options": options,
        "registration_token": token,
        "expires_in": WEBAUTHN_CHALLENGE_TTL_SECONDS,
    })


@router.post("/webauthn/register/complete")
def webauthn_register_complete(
    body: WebAuthnRegisterCompleteRequest,
    db: Session = Depends(get_db),
) -> dict:
    payload, user = _webauthn_user(db, body.registration_token, "register")
    try:
        challenge = unb64url(str(payload.get("challenge") or ""))
        verified = verify_registration(body.credential, challenge)
    except WebAuthnPolicyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:
        logger.warning("Passkey registration verification failed for user %s: %s", user.id, exc)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Passkey registration could not be verified.",
        ) from exc
    name = (body.name or "Passkey").strip()[:80] or "Passkey"
    transports = body.credential.get("response", {}).get("transports")
    if not isinstance(transports, list):
        transports = []
    credential = WebAuthnCredential(
        user_id=user.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=int(verified.sign_count),
        name=name,
        transports=",".join(str(item)[:32] for item in transports)[:255] or None,
        device_type=str(getattr(verified.credential_device_type, "value", "")),
        backed_up=bool(verified.credential_backed_up),
    )
    db.add(credential)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This passkey is already registered.") from exc
    _revoke_webauthn_challenge(payload)
    log_event(
        db,
        PASSKEY_ADDED,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"name": name},
    )
    return ok({
        "credential": {
            "id": b64url(credential.credential_id),
            "name": credential.name,
        },
        "passkey_count": len(_webauthn_credentials(db, user)),
    })


@router.delete("/webauthn/{credential_id}")
def webauthn_delete(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        raw_id = unb64url(credential_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid passkey ID.") from exc
    credential = db.scalar(
        select(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user.id,
            WebAuthnCredential.credential_id == raw_id,
        )
    )
    if credential is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Passkey not found.")
    if _organization_requires_mfa(db, user):
        remaining = len(_webauthn_credentials(db, user)) - 1
        if remaining <= 0 and not user.mfa_enabled:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Your organization requires MFA; this is your only second factor. Add another passkey or enable TOTP first.",
            )
    db.delete(credential)
    db.commit()
    log_event(
        db,
        PASSKEY_REMOVED,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"passkey_id": credential_id},
    )
    return ok({"deleted": True})


@router.post("/webauthn/conditional/options")
def webauthn_conditional_options() -> dict:
    """Return discoverable-credential options for passkey autofill/passwordless login."""
    try:
        options, challenge = authentication_options([])
    except WebAuthnConfigError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ok({
        "options": options,
        "webauthn_token": create_webauthn_conditional_token(challenge),
        "expires_in": WEBAUTHN_CHALLENGE_TTL_SECONDS,
    })


@router.post("/webauthn/conditional/complete")
def webauthn_conditional_complete(
    body: WebAuthnAuthenticateCompleteRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Passwordless passkey login using a discoverable credential."""
    try:
        payload = decode_webauthn_conditional_token(body.webauthn_token.strip())
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Passkey challenge expired or invalid.",
        )
    ip = _client_key(request)
    throttle_key = f"webauthn_conditional:{ip}"
    if login_throttle.is_locked(throttle_key):
        _raise_locked(throttle_key)
    raw_id = _credential_id_from_body(body.credential)
    stored = db.scalar(
        select(WebAuthnCredential).where(WebAuthnCredential.credential_id == raw_id)
    )
    if stored is None:
        login_throttle.record_failure(throttle_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Passkey authentication failed.")
    user = db.get(User, stored.user_id)
    if user is None or not user.active:
        login_throttle.record_failure(throttle_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Passkey authentication failed.")
    try:
        challenge = unb64url(str(payload.get("challenge") or ""))
        verified = verify_authentication(body.credential, challenge, stored)
    except Exception as exc:
        login_throttle.record_failure(throttle_key)
        logger.warning("Conditional passkey authentication failed: %s", exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Passkey authentication failed.",
        ) from exc
    stored.sign_count = int(verified.new_sign_count)
    stored.last_used_at = datetime.now(UTC)
    stored.device_type = str(getattr(verified.credential_device_type, "value", ""))
    stored.backed_up = bool(verified.credential_backed_up)
    db.commit()
    login_throttle.clear(throttle_key)
    _revoke_webauthn_challenge(payload)
    log_event(
        db,
        MFA_VERIFIED,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"method": "webauthn_conditional"},
    )
    log_event(
        db,
        LOGIN,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"method": "passkey", "mfa": "passkey"},
    )
    return ok(_auth_payload(
        user,
        db=db,
        ip_address=ip,
        user_agent=request.headers.get("user-agent", ""),
        remember_device=False,
        auto_renew=True,
    ))


@router.post("/webauthn/authenticate/complete")
def webauthn_authenticate_complete(
    body: WebAuthnAuthenticateCompleteRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    payload, user = _webauthn_user(db, body.webauthn_token, "authenticate")
    ip = _client_key(request)
    throttle_key = f"webauthn:{user.id}:{ip}"
    if login_throttle.is_locked(throttle_key):
        _raise_locked(throttle_key)
    raw_id = _credential_id_from_body(body.credential)
    stored = db.scalar(
        select(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user.id,
            WebAuthnCredential.credential_id == raw_id,
        )
    )
    if stored is None:
        login_throttle.record_failure(throttle_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Passkey is not registered.")
    try:
        challenge = unb64url(str(payload.get("challenge") or ""))
        verified = verify_authentication(body.credential, challenge, stored)
    except Exception as exc:
        login_throttle.record_failure(throttle_key)
        logger.warning("Passkey authentication failed for user %s: %s", user.id, exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Passkey authentication failed.",
        ) from exc
    stored.sign_count = int(verified.new_sign_count)
    stored.last_used_at = datetime.now(UTC)
    stored.device_type = str(getattr(verified.credential_device_type, "value", ""))
    stored.backed_up = bool(verified.credential_backed_up)
    db.commit()
    login_throttle.clear(throttle_key)
    _revoke_webauthn_challenge(payload)
    log_event(
        db,
        MFA_VERIFIED,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"method": "webauthn"},
    )
    log_event(
        db,
        LOGIN,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"method": payload.get("method") or "password", "mfa": "webauthn"},
    )
    return ok(_auth_payload(
        user,
        db=db,
        ip_address=ip,
        user_agent=request.headers.get("user-agent", ""),
        remember_device=bool(payload.get("remember_device", False)),
        auto_renew=bool(payload.get("auto_renew", True)),
    ))


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

    login_method = "password"
    # Local passwords win. LDAP is a fallback for LDAP-managed accounts and
    # for existing local users whose local password is not the one supplied.
    # Deactivated accounts are never eligible for LDAP re-entry.
    if (user is None or user.active) and not valid:
        ldap_user = _try_ldap_login(body.email, body.password, db)
        if ldap_user is not None:
            user = ldap_user
            valid = True
            login_method = "ldap"

    if user is None or not user.active or not valid:
        login_throttle.record_failure(email_key)
        login_throttle.record_failure(ip_key)
        log_event(db, LOGIN_FAILED, target_type="user",
                  target_id=str(user.id) if user else "",
                  detail={"email": body.email.lower()})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    login_throttle.clear(email_key)
    login_throttle.clear(ip_key)
    ip = _client_key(request)
    ua = request.headers.get("user-agent", "")
    passkeys = (
        _webauthn_credentials(db, user)
        if get_settings().webauthn_enabled
        else []
    )
    if user.mfa_enabled or passkeys:
        if user.mfa_enabled and not user.mfa_secret:
            logger.error("MFA enabled without a stored secret for user %s", user.id)
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Multi-factor authentication is temporarily unavailable.",
            )
        payload: dict[str, Any] = {}
        methods: list[str] = []
        if user.mfa_enabled:
            payload.update({
                "mfa_required": True,
                "challenge_token": create_mfa_challenge_token(
                    user.id,
                    remember_device=body.remember_device,
                    auto_renew=body.auto_renew,
                ),
                "expires_in": MFA_CHALLENGE_TTL_SECONDS,
            })
            methods.append("totp")
        if passkeys:
            try:
                options, challenge = authentication_options(passkeys)
            except WebAuthnConfigError as exc:
                logger.error("WebAuthn is misconfigured: %s", exc)
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "Passkey authentication is temporarily unavailable.",
                ) from exc
            payload.update({
                "webauthn_required": True,
                "webauthn_token": create_webauthn_challenge_token(
                    user.id,
                    challenge,
                    "authenticate",
                    remember_device=body.remember_device,
                    auto_renew=body.auto_renew,
                    method=login_method,
                ),
                "webauthn_options": options,
                "webauthn_expires_in": WEBAUTHN_CHALLENGE_TTL_SECONDS,
            })
            methods.append("webauthn")
        log_event(
            db,
            MFA_CHALLENGE,
            target_type="user",
            target_id=str(user.id),
            user_id=user.id,
            detail={"method": login_method, "factors": methods},
        )
        return ok(payload)
    if _organization_requires_mfa(db, user):
        enrollment = create_mfa_enrollment_token(
            user.id,
            remember_device=body.remember_device,
            auto_renew=body.auto_renew,
            method=login_method,
        )
        log_event(
            db,
            MFA_ENROLLMENT_REQUIRED,
            target_type="user",
            target_id=str(user.id),
            user_id=user.id,
            detail={"method": login_method},
        )
        return ok({
            "mfa_enrollment_required": True,
            "enrollment_token": enrollment,
            "expires_in": MFA_ENROLLMENT_TTL_SECONDS,
            "issuer": MFA_ISSUER,
        })
    log_event(
        db,
        LOGIN,
        target_type="user",
        target_id=str(user.id),
        user_id=user.id,
        detail={"method": login_method},
    )
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
        if payload.get("purpose"):
            raise pyjwt.InvalidTokenError("Purpose-scoped token cannot be used as a bearer token.")
        user_id = int(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    if token_is_stale(payload, user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please log in again.")
    return user


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
        "mfa_enabled": bool(user.mfa_enabled),
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
