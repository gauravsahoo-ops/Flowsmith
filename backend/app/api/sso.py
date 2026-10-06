"""Enterprise Single Sign-On (SSO) endpoints (Google, GitHub, OIDC/Okta).

Provides native SSO authentication without enterprise paywalls:
- GET /api/auth/sso/providers: Lists active configured SSO providers.
- GET /api/auth/sso/{provider}/login: Initiates SSO flow, redirects to provider.
- GET /api/auth/sso/{provider}/callback: Exchanges authorization code, finds/provisions user, issues Flowsmith JWT.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import ok
from app.audit import LOGIN, REGISTER, log_event
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.security.jwt import create_token, hash_password

logger = logging.getLogger("sso")

router = APIRouter(prefix="/api/auth/sso", tags=["sso"])

_SSO_STATES: dict[str, tuple[str, float]] = {}
_SSO_STATE_TTL = 600


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
    cfg = _get_provider_config(provider)
    if not cfg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"SSO provider '{provider}' is not configured.")

    state = secrets.token_urlsafe(32)
    import time as _time
    _SSO_STATES[state] = (provider, _time.monotonic())
    _evict_expired_sso_states()

    # Determine callback URL: host header or public URL
    base_url = str(request.base_url).rstrip("/")
    callback_url = f"{base_url}/api/auth/sso/{provider}/callback"

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
    }
    url = f"{cfg['authorize_url']}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


def _evict_expired_sso_states() -> None:
    import time as _time
    now = _time.monotonic()
    expired = [s for s, (_, ts) in _SSO_STATES.items() if now - ts > _SSO_STATE_TTL]
    for s in expired:
        del _SSO_STATES[s]


@router.get("/{provider}/callback")
async def sso_callback(
    provider: str,
    request: Request,
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="CSRF state"),
    db: Session = Depends(get_db),
) -> Any:
    """Handle OAuth2/OIDC code callback, find or provision user, and issue Flowsmith JWT."""
    cfg = _get_provider_config(provider)
    if not cfg:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"SSO provider '{provider}' is not configured.")

    # Validate state (CSRF protection)
    state_entry = _SSO_STATES.pop(state, None)
    if not state_entry or state_entry[0] != provider:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired SSO state parameter.")

    base_url = str(request.base_url).rstrip("/")
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
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to exchange SSO authorization code: {exc}") from exc

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
                email = profile.get("email")
                if not email:
                    # Fetch primary email from GitHub emails API
                    emails_resp = await client.get(
                        "https://api.github.com/user/emails",
                        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                    )
                    emails_list = emails_resp.json()
                    if isinstance(emails_list, list):
                        primary = next((e for e in emails_list if e.get("primary") and e.get("verified")), None)
                        if primary:
                            email = primary.get("email")
                        elif len(emails_list) > 0:
                            email = emails_list[0].get("email")
            else:
                email = profile.get("email")
                name = profile.get("name") or profile.get("given_name") or ""

        except Exception as exc:
            logger.error("Failed to fetch SSO userinfo: %s", exc)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to fetch profile from SSO provider: {exc}") from exc

    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not obtain a verified email address from the SSO provider.")

    email = email.lower().strip()

    # Find or auto-provision user in Flowsmith
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        # First registered user becomes admin
        is_first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role="admin" if is_first else "member",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        log_event(db, REGISTER, target_type="user", target_id=str(user.id), user_id=user.id)

    log_event(db, LOGIN, target_type="user", target_id=str(user.id), user_id=user.id)

    # Issue Flowsmith JWT
    jwt_token = create_token(user.id, email=user.email)

    # Redirect to frontend root with token in fragment or query for secure pickup
    redirect_url = f"/?sso_token={jwt_token}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
