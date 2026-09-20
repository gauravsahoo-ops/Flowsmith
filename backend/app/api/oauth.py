"""OAuth connect endpoints — generic provider framework (Phase 33).

One flow, N providers: ``POST /api/auth/{provider}/connect`` starts the
authorization-code dance and returns the authorize URL; the provider
redirects back to ``GET /api/auth/{provider}/callback`` which exchanges
the code and stores an encrypted credential. Salesforce keeps its legacy
paths/behaviour unchanged (it is simply the first registered provider).

Security properties (enforced here for every provider):

- The app-level client id/secret/redirect URI are SERVER configuration
  (Settings) and are never sent to the frontend.
- `state` is a random value stored in `oauth_states` and bound to the
  authenticated user, so a callback cannot be forged (CSRF) or replayed.
- PKCE is used for providers that support it.
- The refresh token is stored only inside the Fernet-encrypted credential
  blob (never in workflow JSON, execution history, traces, or logs).
- The connection belongs to the user who authorized it; the
  CredentialResolver resolves credentials per executing user, so User A's
  workflow can never use User B's connection.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlparse

from app.credentials.service import create_for_user

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import OAUTH_CONNECT, OAUTH_CONNECT_FAILED, SALESFORCE_CONNECT, SALESFORCE_CONNECT_FAILED, log_event
from app.config import get_settings
from app.db import get_db
from app.models import OAuthState, User
from app.oauth_providers import (
    get_existing_oauth_credential,
    get_provider,
    pkce_pair,
    purge_stale_states,
    replace_oauth_credential,
)
from app.security.safe_http_client import get_safe_http_client

router = APIRouter(prefix="/api/auth", tags=["oauth"])

logger = logging.getLogger("oauth")

# Audit continuity: Salesforce keeps its historical event names.
_AUDIT_MAP = {"salesforce": (SALESFORCE_CONNECT, SALESFORCE_CONNECT_FAILED)}


class ConnectRequest(BaseModel):
    login_url: str | None = Field(
        default=None,
        description="Provider-specific org base (Salesforce only; defaults to SALESFORCE_LOGIN_URL).",
    )


def _audit_names(provider_key: str) -> tuple[str, str]:
    return _AUDIT_MAP.get(provider_key, (OAUTH_CONNECT, OAUTH_CONNECT_FAILED))


def _fail_redirect(frontend_url: str, spec, reason: str) -> RedirectResponse:
    # Dedicated minimal callback page (no full app)
    return RedirectResponse(
        f"{frontend_url}/oauth/callback?provider={quote(spec.key)}&ok=0&error={quote(reason[:200])}",
        status_code=status.HTTP_302_FOUND,
    )


def _resolve_login_url(spec, body: ConnectRequest | None) -> str:
    if not spec.uses_login_url:
        return ""
    settings = get_settings()
    return (
        (body.login_url if body else None)
        or settings.salesforce_login_url
        or "https://login.salesforce.com"
    ).rstrip("/")


@router.post("/{provider}/connect")
def connect_provider(
    provider: str,
    body: ConnectRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Start the OAuth authorization flow.

    Returns the authorize URL the frontend opens in a popup / new tab.
    The state is recorded server-side and bound to the user.
    """
    spec = get_provider(provider)
    assert spec.authorize_url is not None, f"provider {provider} misconfigured"
    purge_stale_states(db)
    client_id, _client_secret, redirect_uri = spec.server_config(get_settings())
    login_url = _resolve_login_url(spec, body)

    verifier, challenge = ("", "")
    if spec.supports_pkce:
        verifier, challenge = pkce_pair()

    from secrets import token_urlsafe

    state = token_urlsafe(32)
    db.add(OAuthState(state=state, user_id=user.id, login_url=login_url, code_verifier=verifier))
    db.commit()

    authorize_url = spec.authorize_url(
        get_settings(), state=state, challenge=challenge, login_url=login_url
    )
    return ok({"authorize_url": authorize_url, "state": state})


@router.get("/{provider}/callback")
async def provider_callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
):
    """OAuth callback: validate state, exchange the code, store the
    encrypted connection, then redirect back to the frontend.

    On any failure the user is redirected to the frontend with the
    provider's failure marker so the UI can surface the error.
    """
    spec = get_provider(provider)
    audit_ok, audit_fail = _audit_names(provider)
    settings = get_settings()
    frontend_url = (settings.public_url or str(request.base_url)).rstrip("/")

    if error:
        reason = error_description or error
        log_event(db, audit_fail, target_type="credential", detail={"reason": reason[:200], "provider": provider})
        return _fail_redirect(frontend_url, spec, reason)

    if not code or not state:
        return _fail_redirect(frontend_url, spec, "missing code or state")

    row = db.get(OAuthState, state)
    if row is None:
        return _fail_redirect(frontend_url, spec, "invalid state")
    if row.used:
        return _fail_redirect(frontend_url, spec, "state already used")
    created = row.created_at
    if created.tzinfo is None:  # SQLite stores naive UTC datetimes
        created = created.replace(tzinfo=UTC)
    age = datetime.now(UTC) - created
    if age > timedelta(seconds=settings.oauth_state_ttl_seconds):
        return _fail_redirect(frontend_url, spec, "state expired")
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        return _fail_redirect(frontend_url, spec, "invalid user")

    # Mark used before the exchange so the code/state pair cannot replay.
    row.used = True
    db.commit()

    client_id, client_secret, redirect_uri = spec.server_config(settings)
    login_url = (row.login_url or "").rstrip("/")

    assert spec.token_request is not None and spec.token_headers is not None, f'provider {provider} misconfigured'
    url, body = spec.token_request(
        settings, code=code, verifier=row.code_verifier or "", redirect_uri=redirect_uri, login_url=login_url
    )
    try:
        async with get_safe_http_client() as client:
            response = await client.request(
                "POST",
                url,
                data=body,
                headers=spec.token_headers(),
                timeout=30.0,
            )
    except Exception as exc:  # SSRF/timeouts/network errors
        logger.warning("%s token exchange failed for user %s: %s", provider, row.user_id, exc)
        log_event(db, audit_fail, target_type="credential", detail={"reason": "token exchange failed", "provider": provider})
        return _fail_redirect(frontend_url, spec, "token exchange failed")

    if response.status_code >= 400:
        reason = "token exchange rejected"
        try:
            err = response.json()
            if isinstance(err, dict):
                reason = err.get("error_description") or err.get("error") or reason
        except ValueError:
            pass
        logger.warning("%s token exchange rejected for user %s: %s", provider, row.user_id, reason)
        log_event(db, audit_fail, target_type="credential", detail={"reason": str(reason)[:200], "provider": provider})
        return _fail_redirect(frontend_url, spec, reason)

    try:
        payload = response.json()
        refresh_token = payload["refresh_token"]
    except (ValueError, KeyError):
        logger.warning("%s token response malformed for user %s", provider, row.user_id)
        log_event(db, audit_fail, target_type="credential", detail={"reason": "token response malformed", "provider": provider})
        return _fail_redirect(frontend_url, spec, "token response malformed")

    # Best-effort identity lookup for a friendly display label; the access
    # token is used here and discarded immediately; never persisted.
    label = ""
    if spec.identity_label is not None:
        async with get_safe_http_client() as client:
            label = await spec.identity_label(client, settings, payload)

    host = ""
    if login_url:
        try:
            host = (urlparse(login_url).hostname or "").split(".")[0]
        except Exception:
            host = ""

    # Reconnect semantics: keep a single active OAuth connection per user
    # and provider. Reuse the existing credential record if present so workflows
    # referencing its ID continue working uninterrupted.
    existing_rec = get_existing_oauth_credential(db, user, spec.credential_type)

    assert spec.credential_data is not None, f"provider {provider} misconfigured"
    data = spec.credential_data(settings, payload, login_url, label)
    name = f"{spec.display_name} ({label or host or data.get('hub_id') or 'connected'})"

    if existing_rec is not None:
        from app.security.crypto import encrypt_text
        existing_rec.name = name
        existing_rec.data = encrypt_text(json.dumps(data))
        replace_oauth_credential(db, user, spec.credential_type, keep_id=existing_rec.id)
        db.commit()
        db.refresh(existing_rec)
        meta = {"id": existing_rec.id, "name": existing_rec.name, "type": existing_rec.type}
    else:
        replace_oauth_credential(db, user, spec.credential_type)
        try:
            meta = create_for_user(
                db, user.id, name, spec.credential_type, data
            )
        except Exception as exc:
            logger.warning("credential creation failed for user %s: %s", user.id, exc)
            log_event(db, audit_fail, target_type="credential", detail={"reason": "credential save failed", "provider": provider})
            return _fail_redirect(frontend_url, spec, "credential save failed")

    log_event(
        db, audit_ok,
        target_type="credential", target_id=meta["id"], user_id=user.id,
        detail={"name": name, "provider": provider},
    )

    return RedirectResponse(
        f"{frontend_url}/oauth/callback?provider={quote(provider)}&ok=1",
        status_code=status.HTTP_302_FOUND,
    )


