"""Enterprise Single Sign-On (SSO) endpoints (Google, GitHub, OIDC/Okta).

Provides native SSO authentication without enterprise paywalls:
- GET /api/auth/sso/providers: Lists active configured SSO providers.
- GET /api/auth/sso/{provider}/login: Initiates SSO flow, redirects to provider.
- GET /api/auth/sso/{provider}/callback: Exchanges authorization code, finds/provisions user, issues Flowsmith JWT.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import ok
from app.audit import LOGIN, REGISTER, log_event
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.security.jwt import _get_jwt_secret, create_token, hash_password

logger = logging.getLogger("sso")

router = APIRouter(prefix="/api/auth/sso", tags=["sso"])

_SSO_STATE_COOKIE = "flowsmith_sso_state"
_SSO_STATE_TTL = 600
_SSO_STATE_ALGORITHM = "HS256"


def _get_provider_config(provider: str) -> dict[str, Any] | None:
    settings = get_settings()
    provider = provider.lower()
    if provider == "google":
        if not settings.sso_google_client_id or not settings.sso_google_client_secret:
            return None
        return {
            "id": "google",
            "name": "Google",
            "icon": "google",
            "client_id": settings.sso_google_client_id,
            "client_secret": settings.sso_google_client_secret,
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
            "scope": "openid email profile",
        }
    if provider == "github":
        if not settings.sso_github_client_id or not settings.sso_github_client_secret:
            return None
        return {
            "id": "github",
            "name": "GitHub",
            "icon": "github",
            "client_id": settings.sso_github_client_id,
            "client_secret": settings.sso_github_client_secret,
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            "scope": "read:user user:email",
        }
    if provider in ("oidc", "okta", "saml"):
        if not settings.sso_oidc_client_id or not settings.sso_oidc_client_secret:
            return None
        issuer = (settings.sso_oidc_issuer or "").rstrip("/")
        return {
            "id": "oidc",
            "name": settings.sso_oidc_display_name or "Enterprise SSO",
            "icon": "shield",
            "client_id": settings.sso_oidc_client_id,
            "client_secret": settings.sso_oidc_client_secret,
            "authorize_url": f"{issuer}/protocol/openid-connect/auth" if "keycloak" in issuer else f"{issuer}/authorize",
            "token_url": f"{issuer}/protocol/openid-connect/token" if "keycloak" in issuer else f"{issuer}/oauth/token",
            "userinfo_url": f"{issuer}/protocol/openid-connect/userinfo" if "keycloak" in issuer else f"{issuer}/userinfo",
            "scope": "openid email profile",
        }
    return None


def _sso_base_url(request: Request) -> str:
    """Trusted base URL for callback construction.

    Never derive OAuth redirect URIs from the Host header in production: a
    forged Host changes the redirect_uri sent to the identity provider and
    can split the flow across attacker-controlled origins.
    """
    settings = get_settings()
    configured = (settings.public_url or "").strip().rstrip("/")
    if configured:
        return configured
    if settings.app_env == "development":
        return str(request.base_url).rstrip("/")
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "PUBLIC_URL must be configured for SSO in production.",
    )


def _cookie_secure(request: Request) -> bool:
    settings = get_settings()
    if (settings.public_url or "").lower().startswith("https://"):
        return True
    return request.url.scheme == "https"


def _new_sso_state(provider: str) -> tuple[str, str]:
    """Return a signed, stateless state token and its browser-binding nonce."""
    nonce = secrets.token_urlsafe(24)
    now = datetime.now(UTC)
    token = pyjwt.encode(
        {
            "sub": "sso_state",
            "provider": provider,
            "nonce": nonce,
            "iat": now,
            "exp": now + timedelta(seconds=_SSO_STATE_TTL),
        },
        _get_jwt_secret(),
        algorithm=_SSO_STATE_ALGORITHM,
    )
    return token, nonce


def _verify_sso_state(state: str, provider: str, cookie_nonce: str | None) -> None:
    if not cookie_nonce:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired SSO state parameter.")
    try:
        payload = pyjwt.decode(
            state,
            _get_jwt_secret(),
            algorithms=[_SSO_STATE_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired SSO state parameter."
        ) from exc
    nonce = str(payload.get("nonce") or "")
    if (
        payload.get("sub") != "sso_state"
        or payload.get("provider") != provider
        or not nonce
        or not hmac.compare_digest(nonce, cookie_nonce)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired SSO state parameter.")


@router.get("/providers")
def list_sso_providers() -> dict:
    """List configured SSO providers available for login."""
    providers = []
    for p_id in ("google", "github", "oidc"):
        cfg = _get_provider_config(p_id)
        if cfg:
            providers.append({
                "id": cfg["id"],
                "name": cfg["name"],
                "icon": cfg["icon"],
            })
    return ok(providers)


@router.get("/{provider}/login")
def sso_login(provider: str, request: Request) -> Any:
    """Initiate SSO login and redirect to identity provider."""
    provider = provider.lower()
    cfg = _get_provider_config(provider)
    if not cfg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"SSO provider '{provider}' is not configured.")

    state, nonce = _new_sso_state(cfg["id"])
    base_url = _sso_base_url(request)
    callback_url = f"{base_url}/api/auth/sso/{provider}/callback"

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
    }
    url = f"{cfg['authorize_url']}?{urlencode(params)}"
    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    # Bind the signed state to this browser. The state token itself is
    # stateless, so multi-replica deployments need no shared session store.
    response.set_cookie(
        _SSO_STATE_COOKIE,
        nonce,
        max_age=_SSO_STATE_TTL,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/api/auth/sso",
    )
    return response


@router.get("/{provider}/callback")
async def sso_callback(
    provider: str,
    request: Request,
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="CSRF state"),
    db: Session = Depends(get_db),
) -> Any:
    """Handle OAuth2/OIDC code callback, find or provision user, and issue Flowsmith JWT."""
    provider = provider.lower()
    cfg = _get_provider_config(provider)
    if not cfg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"SSO provider '{provider}' is not configured.")

    # Validate the signed state and its HttpOnly browser-binding nonce.
    _verify_sso_state(state, cfg["id"], request.cookies.get(_SSO_STATE_COOKIE))

    base_url = _sso_base_url(request)
    callback_url = f"{base_url}/api/auth/sso/{provider}/callback"

    # Exchange code for access token
    token_data: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            token_resp = await client.post(
                cfg["token_url"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": callback_url,
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                },
                headers={"Accept": "application/json"},
            )
            token_data = token_resp.json()
        except Exception as exc:
            logger.error("Failed to exchange SSO code: %s", exc)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to exchange SSO authorization code.") from exc

        access_token = token_data.get("access_token")
        if not access_token:
            error_desc = token_data.get("error_description") or token_data.get("error") or "No access token in response"
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"SSO token exchange failed: {error_desc}")

        # Fetch user profile
        email: str | None = None
        name: str = ""
        try:
            profile_resp = await client.get(
                cfg["userinfo_url"],
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            profile = profile_resp.json()

            if provider == "github":
                name = profile.get("name") or profile.get("login") or ""
                # Never trust profile.email blindly - always resolve through
                # the emails API and require a VERIFIED address (unverified
                # addresses would allow account takeover).
                email = None
                emails_resp = await client.get(
                    "https://api.github.com/user/emails",
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                )
                emails_list = emails_resp.json()
                if isinstance(emails_list, list):
                    primary = next((e for e in emails_list if e.get("primary") and e.get("verified")), None)
                    if primary:
                        email = primary.get("email")
                    else:
                        verified = next((e for e in emails_list if e.get("verified")), None)
                        email = verified.get("email") if verified else None
            else:
                email = profile.get("email")
                # OIDC/Google: reject explicitly unverified emails.
                if profile.get("email_verified") is False:
                    email = None
                name = profile.get("name") or profile.get("given_name") or ""

        except Exception as exc:
            logger.error("Failed to fetch SSO userinfo: %s", exc)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to fetch profile from SSO provider.") from exc

    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not obtain a verified email address from the SSO provider.")

    email = email.lower().strip()

    # Find or auto-provision user in Flowsmith
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and not user.active:
        # Deactivated accounts must not regain access through SSO.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated.")
    if not user:
        # Auto-provisioning obeys the same registration policy as password
        # signup. The first account always bootstraps as admin; after that,
        # closed/invite installations require an admin-created user (which
        # SSO then links by verified email).
        settings = get_settings()
        mode = (settings.registration_mode or "open").strip().lower()
        from app.api.auth import _BOOTSTRAP_ADVISORY_KEY, _REGISTRATION_BOOTSTRAP_LOCK

        with _REGISTRATION_BOOTSTRAP_LOCK:
            try:
                if db.get_bind().dialect.name == "postgresql":
                    db.execute(
                        text("SELECT pg_advisory_xact_lock(:key)"),
                        {"key": _BOOTSTRAP_ADVISORY_KEY},
                    )
                # Re-check under the lock: another replica may have created
                # this email (or the first admin) while we fetched the profile.
                user = db.scalar(select(User).where(User.email == email))
                if user is not None and not user.active:
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN, "This account has been deactivated."
                    )
                if user is None:
                    is_first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
                    if is_first and settings.registration_bootstrap_token:
                        raise HTTPException(
                            status.HTTP_403_FORBIDDEN,
                            "The first admin must be created with the password bootstrap flow.",
                        )
                    if not is_first and mode != "open":
                        raise HTTPException(
                            status.HTTP_403_FORBIDDEN,
                            "SSO auto-provisioning is disabled. Contact an administrator.",
                        )
                    user = User(
                        email=email,
                        password_hash=hash_password(secrets.token_urlsafe(32)),
                        role="admin" if is_first else "member",
                    )
                    db.add(user)
                    db.commit()
                    db.refresh(user)
                    log_event(db, REGISTER, target_type="user", target_id=str(user.id), user_id=user.id)
            except IntegrityError as exc:
                db.rollback()
                user = db.scalar(select(User).where(User.email == email))
                if user is None or not user.active:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT, "Could not provision the SSO account."
                    ) from exc
            except Exception:
                db.rollback()
                raise

    log_event(db, LOGIN, target_type="user", target_id=str(user.id), user_id=user.id)

    # Issue Flowsmith JWT
    jwt_token = create_token(user.id, email=user.email)

    # Redirect to frontend root with the token in the URL *fragment* so it
    # never reaches server/proxy logs, browser history queries, or Referer.
    redirect_url = f"/#sso_token={jwt_token}"
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(
        _SSO_STATE_COOKIE,
        path="/api/auth/sso",
        secure=_cookie_secure(request),
        httponly=True,
        samesite="lax",
    )
    return response
