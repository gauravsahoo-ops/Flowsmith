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

import json
import logging
from datetime import UTC, datetime, timedelta
from secrets import compare_digest, token_urlsafe
from typing import Any
from urllib.parse import quote, urlparse

from app.credentials.service import create_for_user

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
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
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }

    login_url: str | None = Field(
        default=None,
        description="Provider-specific org base (Salesforce only; defaults to SALESFORCE_LOGIN_URL).",
    )
    prompt: str | None = Field(
        default=None,
        description="OAuth prompt parameter (e.g. 'login' to force account selection / re-login).",
    )
    client_id: str | None = Field(
        default=None,
        description="Optional client ID override (from manual configuration or UI).",
    )
    client_secret: str | None = Field(
        default=None,
        description="Optional client secret override (from manual configuration or UI).",
    )
    credential_id: str | None = Field(
        default=None,
        description="Optional existing credential ID to inherit client credentials and login URL from.",
    )
    name: str | None = Field(
        default=None,
        description="Optional custom credential name (e.g. 'Salesforce account 2').",
    )
    allowed_domains: str | None = Field(
        default=None,
        description="Allowed HTTP request domains policy (e.g. 'all', 'specific', 'none').",
    )
    tenant_id: str | None = Field(
        default=None,
        description="Optional tenant ID override (for Microsoft Dynamics 365 / Azure Entra).",
    )

    @model_validator(mode="before")
    @classmethod
    def _remap_camel_case(cls, data: Any) -> Any:
        if isinstance(data, dict):
            mapped = dict(data)
            if "clientId" in mapped and "client_id" not in mapped:
                mapped["client_id"] = mapped["clientId"]
            if "clientSecret" in mapped and "client_secret" not in mapped:
                mapped["client_secret"] = mapped["clientSecret"]
            if "loginUrl" in mapped and "login_url" not in mapped:
                mapped["login_url"] = mapped["loginUrl"]
            if "credentialId" in mapped and "credential_id" not in mapped:
                mapped["credential_id"] = mapped["credentialId"]
            if "allowedDomains" in mapped and "allowed_domains" not in mapped:
                mapped["allowed_domains"] = mapped["allowedDomains"]
            if "tenantId" in mapped and "tenant_id" not in mapped:
                mapped["tenant_id"] = mapped["tenantId"]
            return mapped
        return data


def _audit_names(provider_key: str) -> tuple[str, str]:
    return _AUDIT_MAP.get(provider_key, (OAUTH_CONNECT, OAUTH_CONNECT_FAILED))


def _fail_redirect(frontend_url: str, spec, reason: str) -> RedirectResponse:
    # Dedicated minimal callback page (no full app)
    return RedirectResponse(
        f"{frontend_url}/oauth/callback?provider={quote(spec.key)}&ok=0&error={quote(reason[:200])}",
        status_code=status.HTTP_302_FOUND,
    )


def _resolve_login_url(spec, body: ConnectRequest | None, db: Session | None = None, user_id: int | None = None) -> str:
    if not spec.uses_login_url:
        return ""
    if body and body.login_url:
        return body.login_url.rstrip("/")
    if db is not None:
        try:
            import json
            from sqlalchemy import select
            from app.models.credential import Credential
            from app.security.crypto import decrypt_text

            types_to_check = [
                spec.credential_type,
                f"{spec.credential_type}_oauth_config",
                f"{spec.key}_oauth_config",
                spec.key,
            ]
            query = select(Credential).where(Credential.type.in_(types_to_check))
            if user_id:
                query = query.where(Credential.user_id == user_id)
            for rec in db.scalars(query.order_by(Credential.created_at.desc())).all():
                try:
                    d = json.loads(decrypt_text(rec.data))
                    db_url = (d.get("login_url") or d.get("instance_url") or "").strip()
                    if db_url and db_url.startswith("http"):
                        return db_url.rstrip("/")
                except Exception:
                    continue
        except Exception:
            pass
    settings = get_settings()
    if spec.key == "dynamics_crm":
        return (getattr(settings, "dynamics_crm_instance_url", "") or "").rstrip("/")
    return (
        settings.salesforce_login_url
        or "https://login.salesforce.com"
    ).rstrip("/")


_SF_LOGIN_HOST_SUFFIXES = (".salesforce.com", ".salesforce.mil")
_DYN_LOGIN_HOST_SUFFIXES = (
    ".crm.dynamics.com",
    ".dynamics.com",
    ".dynamics365.com",
    ".microsoftonline.com",
)


def _validate_login_url(spec, raw: str) -> str:
    """Reject login_url values outside the provider's trusted hosts.

    The Salesforce token exchange POSTs the OAuth client_secret to
    ``{login_url}/services/oauth2/token``; an attacker-controlled login_url
    would exfiltrate the Connected App consumer secret, and a rogue Dynamics
    instance host would receive bearer access tokens.
    """
    url = (raw or "").strip()
    if not url or not spec.uses_login_url:
        return url
    host = ""
    if url.startswith(("http://", "https://")):
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "login_url must use https"
            )
        host = (parsed.hostname or "").lower()
    else:
        if spec.key == "dynamics_crm" and "/" not in url:
            # Bare Azure AD tenant id ("common", "organizations", a GUID) — no host.
            return url
        host = url.split("/")[0].split(":")[0].lower()
    if spec.key == "salesforce":
        allowed = _SF_LOGIN_HOST_SUFFIXES
    elif spec.key == "dynamics_crm":
        allowed = _DYN_LOGIN_HOST_SUFFIXES
    else:
        allowed = ()
    if not any(host.endswith(suffix) for suffix in allowed):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"login_url host '{host}' is not an allowed {spec.display_name} login host",
        )
    return url


@router.post("/{provider}/connect")
def connect_provider(
    provider: str,
    response: Response,
    body: ConnectRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Start the OAuth authorization flow.

    Returns the authorize URL the frontend opens in a popup / new tab.
    The state is recorded server-side and bound to the user, and a
    short-lived HttpOnly cookie binds the callback to this browser.
    """
    settings = get_settings()
    spec = get_provider(provider)
    if spec.authorize_url is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"provider {provider} misconfigured")
    purge_stale_states(db)
    body_cid = (body.client_id or "").strip() if body else ""
    body_sec = (body.client_secret or "").strip() if body else ""
    login_url = ""

    if body and body.credential_id:
        from app.models.credential import Credential
        from app.security.crypto import decrypt_text
        target_cred = db.get(Credential, body.credential_id)
        if target_cred and target_cred.user_id == user.id:
            try:
                c_data = json.loads(decrypt_text(target_cred.data))
                body_cid = body_cid or (c_data.get("client_id") or "").strip()
                body_sec = body_sec or (c_data.get("client_secret") or "").strip()
                if not (body and body.login_url):
                    login_url = (c_data.get("login_url") or c_data.get("instance_url") or "").strip().rstrip("/")
            except Exception:
                pass

    db_config = None
    if db is not None and not (body_cid and body_sec):
        db_config = spec.database_config(db, user.id)
    if db_config and not body_cid and not body_sec:
        # Bind a database-only Connected App to this connection so every
        # provider can refresh later without relying on process-wide env vars.
        body_cid, body_sec, _ = db_config

    client_id, _resolved_secret, redirect_uri = spec.server_config(
        get_settings(), db=db, user_id=user.id, client_id=body_cid, client_secret=body_sec
    )
    if not login_url:
        login_url = _resolve_login_url(spec, body, db=db, user_id=user.id)
    login_url = _validate_login_url(spec, login_url)

    verifier, challenge = ("", "")
    if spec.supports_pkce:
        verifier, challenge = pkce_pair()

    enc_sec = None
    if body_sec:
        from app.security.crypto import encrypt_text
        enc_sec = encrypt_text(body_sec).decode("utf-8")

    state = token_urlsafe(32)
    oauth_row = OAuthState(
        state=state,
        user_id=user.id,
        login_url=login_url,
        code_verifier=verifier,
        client_id=body_cid or None,
        client_secret=enc_sec,
        name=body.name.strip() if (body and body.name and body.name.strip()) else None,
        allowed_domains=body.allowed_domains.strip() if (body and body.allowed_domains and body.allowed_domains.strip()) else None,
    )
    db.add(oauth_row)
    try:
        db.commit()
    except Exception as exc:
        # Schema changes belong to migrations. Running DDL from a request
        # path is unsafe under concurrency and can block behind table locks;
        # fail clearly instead of silently mutating production schema.
        db.rollback()
        logger.error("Failed to store OAuthState: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Failed to record OAuth session state.",
        ) from exc

    prompt = (body.prompt or "").strip() if body else ""
    try:
        authorize_url = spec.authorize_url(
            get_settings(),
            state=state,
            challenge=challenge,
            login_url=login_url,
            prompt=prompt,
            client_id=client_id,
            redirect_uri=redirect_uri,
            db=db,
            user_id=user.id,
            tenant_id=body.tenant_id if body else None,
        )
    except TypeError:
        try:
            authorize_url = spec.authorize_url(
                get_settings(), state=state, challenge=challenge, login_url=login_url, prompt=prompt
            )
        except TypeError:
            authorize_url = spec.authorize_url(
                get_settings(), state=state, challenge=challenge, login_url=login_url
            )
    response.set_cookie(
        key=f"oauth_state_{provider}",
        value=state,
        max_age=max(60, int(settings.oauth_state_ttl_seconds)),
        httponly=True,
        samesite="lax",
        secure=bool((settings.public_url or "").strip().lower().startswith("https://")),
        path="/api/auth",
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

    # The state row binds the flow to the user who started it; the HttpOnly
    # cookie binds it to the browser that started it. Without this check an
    # attacker could hand another user their authorize URL and have the
    # resulting tokens stored on the attacker's account (login CSRF).
    state_cookie = request.cookies.get(f"oauth_state_{provider}") or ""
    if not state_cookie or not compare_digest(state_cookie, state):
        return _fail_redirect(frontend_url, spec, "invalid state")

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

    raw_secret = getattr(row, "client_secret", None)
    decrypted_secret = None
    if raw_secret:
        try:
            from app.security.crypto import decrypt_text
            decrypted_secret = decrypt_text(raw_secret)
        except Exception:
            decrypted_secret = raw_secret

    client_id, client_secret, redirect_uri = spec.server_config(
        settings,
        db=db,
        user_id=user.id,
        client_id=getattr(row, "client_id", None),
        client_secret=decrypted_secret,
    )
    login_url = (row.login_url or "").rstrip("/")
    try:
        login_url = _validate_login_url(spec, login_url)
    except HTTPException:
        logger.warning("%s rejected stored login_url for user %s", provider, row.user_id)
        return _fail_redirect(frontend_url, spec, "untrusted login_url")

    if spec.token_request is None or spec.token_headers is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"provider {provider} misconfigured")
    try:
        url, body = spec.token_request(
            settings,
            code=code,
            verifier=row.code_verifier or "",
            redirect_uri=redirect_uri,
            login_url=login_url,
            client_id=client_id,
            client_secret=client_secret,
            db=db,
            user_id=user.id,
        )
    except TypeError:
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
        err_msg = str(exc).strip() or type(exc).__name__
        reason = f"token exchange failed: {err_msg}"
        logger.warning("%s token exchange failed for user %s: %s", provider, row.user_id, exc)
        log_event(db, audit_fail, target_type="credential", detail={"reason": reason[:200], "provider": provider})
        return _fail_redirect(frontend_url, spec, reason)

    if response.status_code >= 400:
        reason = "token exchange rejected"
        try:
            err = response.json()
            if isinstance(err, dict):
                reason = err.get("error_description") or err.get("error") or reason
            elif isinstance(err, list) and len(err) > 0 and isinstance(err[0], dict):
                reason = err[0].get("message") or err[0].get("errorCode") or reason
        except ValueError:
            if response.text and len(response.text) < 200:
                reason = f"token exchange rejected ({response.status_code}): {response.text.strip()}"
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

    if spec.credential_data is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"provider {provider} misconfigured")
    has_custom = bool(getattr(row, "client_id", None))
    try:
        data = spec.credential_data(
            settings,
            payload,
            login_url,
            label,
            client_id=client_id,
            client_secret=client_secret,
            has_custom_credentials=has_custom,
        )
    except TypeError:
        data = spec.credential_data(settings, payload, login_url, label)

    if getattr(row, "allowed_domains", None):
        data["allowed_domains"] = row.allowed_domains

    custom_name = getattr(row, "name", None)
    name = custom_name or f"{spec.display_name} ({label or host or data.get('hub_id') or 'connected'})"

    # Multi-account support: match by account identity (username/org/hub_id)
    # Reconnecting the same account updates its tokens; connecting a distinct account
    # creates a new separate credential row so multiple accounts can coexist.
    existing_rec = get_existing_oauth_credential(db, user, spec.credential_type, account_data=data)

    if existing_rec is not None:
        from app.security.crypto import encrypt_text, decrypt_text
        try:
            prev_data = json.loads(decrypt_text(existing_rec.data))
            if not data.get("client_id") and prev_data.get("client_id"):
                data["client_id"] = prev_data["client_id"]
            if not data.get("client_secret") and prev_data.get("client_secret"):
                data["client_secret"] = prev_data["client_secret"]
            if not data.get("login_url") and prev_data.get("login_url"):
                data["login_url"] = prev_data["login_url"]
        except Exception:
            pass
        existing_rec.name = name
        existing_rec.data = encrypt_text(json.dumps(data))
        replace_oauth_credential(db, user, spec.credential_type, keep_id=existing_rec.id, account_data=data)
        db.commit()
        db.refresh(existing_rec)
        meta = {"id": existing_rec.id, "name": existing_rec.name, "type": existing_rec.type}
    else:
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


