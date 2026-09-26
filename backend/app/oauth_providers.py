"""Generic OAuth2 authorization-code provider framework (Phase 33).

One contract, multiple providers: Salesforce (the reference connector)
and HubSpot (the second first-party connector) both plug in here. The
framework owns the security-critical parts once:

- server-side client id/secret (never sent to the frontend),
- single-use, TTL-bound ``state`` bound to the authenticated user,
- PKCE where supported,
- refresh tokens stored only inside Fernet-encrypted credentials,
- audit events + frontend redirect markers per provider.

A provider registers an :class:`OAuthProviderSpec` describing only what
differs: URLs, request shapes, identity lookup for a friendly display
label, and the encrypted credential blob it stores.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.credentials import service as credential_service
from app.models import OAuthState, User
from app.security.crypto import decrypt_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OAuthProviderSpec:
    """Everything that differs between OAuth2 providers."""

    key: str  # "salesforce" | "hubspot"
    display_name: str
    credential_type: str  # stored credential type key
    # Audit event names (existing constants keep history continuity).
    audit_connected: str
    audit_failed: str
    # Frontend redirect markers (App.jsx listens for these).
    marker_ok: str  # e.g. "salesforce_connected" | "oauth_connected"
    marker_failed: str
    scopes_setting: str = ""
    config_prefix: str = ""  # settings prefix; defaults to key
    supports_pkce: bool = True
    uses_login_url: bool = False  # Salesforce lets users pick their org base

    def server_config(
        self,
        settings: Settings,
        db: Any = None,
        user_id: int | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
    ) -> tuple[str, str, str]:
        """(client_id, client_secret, redirect_uri) or HTTP 422.

        Resolves client credentials from explicit arguments first, Settings (env vars) second,
        and falls back to encrypted database credentials so credentials stay encrypted in
        the database only without requiring plain text secrets in config files.
        """
        prefix = self.config_prefix or self.key
        cid = (client_id or "").strip()
        csecret = (client_secret or "").strip()
        redirect = (redirect_uri or "").strip()

        # Prioritize encrypted database credentials so secrets never need to live in plaintext .env
        if db is not None:
            try:
                import json
                from sqlalchemy import select
                from app.models.credential import Credential
                from app.security.crypto import decrypt_text

                prefix = self.config_prefix or self.key
                types_to_check = [
                    f"{self.credential_type}_oauth_config",
                    f"{self.key}_oauth_config",
                    f"{prefix}_oauth_config",
                    self.credential_type,
                    self.key,
                    prefix,
                ]
                query = select(Credential).where(Credential.type.in_(types_to_check))
                candidates = []
                if user_id:
                    candidates = list(
                        db.scalars(query.where(Credential.user_id == user_id).order_by(Credential.created_at.desc())).all()
                    )
                if not candidates:
                    candidates = list(db.scalars(query.order_by(Credential.created_at.desc())).all())

                for cand in candidates:
                    try:
                        data = json.loads(decrypt_text(cand.data))
                        cand_cid = (data.get("client_id") or "").strip()
                        cand_sec = (data.get("client_secret") or "").strip()
                        cand_red = (data.get("redirect_uri") or "").strip()
                        if cand_cid and cand_sec:
                            cid = cid or cand_cid
                            csecret = csecret or cand_sec
                            if cand_red and not redirect:
                                redirect = cand_red
                            break
                    except Exception:
                        continue
            except Exception as exc:
                logger.debug("Could not resolve credentials from database: %s", exc)

        cid = cid or getattr(settings, f"{prefix}_client_id", "")
        csecret = csecret or getattr(settings, f"{prefix}_client_secret", "")
        redirect = redirect or getattr(settings, f"{prefix}_redirect_uri", "")

        if not redirect:
            # Derive from the public URL when not pinned explicitly.
            base = (getattr(settings, "public_url", "") or "").rstrip("/")
            if base:
                redirect = f"{base}/api/auth/{self.key}/callback"
            else:
                redirect = f"https://flowsmith.dev.idslogic.net/api/auth/{self.key}/callback"

        if not cid or not csecret:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{self.display_name} OAuth is not configured on the server or in database "
                f"({self.key.upper()}_CLIENT_ID/{self.key.upper()}_CLIENT_SECRET).",
            )
        if not redirect:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{self.display_name} OAuth is not configured on the server "
                f"({self.key.upper()}_REDIRECT_URI or PUBLIC_URL).",
            )
        return cid, csecret, redirect

    def scopes(self, settings: Settings) -> str:
        return getattr(settings, self.scopes_setting, "") if self.scopes_setting else ""

    # Provider-specific behaviour (set by register_provider).
    authorize_url: Callable[..., str] | None = None  # (settings, state, challenge, login_url, prompt) -> url
    token_request: Callable[..., tuple[str, str]] | None = None  # (settings, code, verifier, redirect_uri, login_url) -> (url, body)
    token_headers: Callable[[], dict[str, str]] | None = None  # () -> extra headers
    identity_label: Callable[..., Any] | None = None  # async (http_client, settings, token_payload) -> label
    credential_data: Callable[..., dict[str, Any]] | None = None  # (settings, token_payload, login_url, label) -> blob
    revoke_token: Callable[..., Any] | None = None  # async (http_client, settings, credential_data) -> bool


def _sf_authorize_url(
    settings: Settings,
    *,
    state: str,
    challenge: str,
    login_url: str,
    prompt: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    db: Any = None,
    user_id: int | None = None,
    **kwargs: Any,
) -> str:
    from urllib.parse import urlencode

    cid = client_id
    r_uri = redirect_uri
    if not cid or not r_uri:
        resolved_cid, _secret, resolved_r_uri = SALESFORCE.server_config(
            settings, db=db, user_id=user_id, client_id=client_id, redirect_uri=redirect_uri
        )
        cid = cid or resolved_cid
        r_uri = r_uri or resolved_r_uri

    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": r_uri,
        "scope": SALESFORCE.scopes(settings),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    effective_prompt = (prompt or "").strip() or "login"
    if effective_prompt:
        params["prompt"] = effective_prompt
    return (
        f"{login_url.rstrip('/')}/services/oauth2/authorize?"
        + urlencode(params)
    )


def _sf_token_request(
    settings: Settings,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
    login_url: str,
    client_id: str = "",
    client_secret: str = "",
    db: Any = None,
    user_id: int | None = None,
    **kwargs: Any,
) -> tuple[str, str]:
    from urllib.parse import urlencode

    cid = (client_id or "").strip() or getattr(settings, "salesforce_client_id", "")
    csec = (client_secret or "").strip() or getattr(settings, "salesforce_client_secret", "")
    if not cid or not csec:
        try:
            cid_sc, csec_sc, _ = SALESFORCE.server_config(
                settings, db=db, user_id=user_id, client_id=client_id, client_secret=client_secret
            )
            cid = cid or cid_sc
            csec = csec or csec_sc
        except Exception:
            pass

    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": cid or getattr(settings, "salesforce_client_id", ""),
        "client_secret": csec or getattr(settings, "salesforce_client_secret", ""),
        "redirect_uri": redirect_uri,
        "code_verifier": verifier or "",
    })
    return f"{login_url.rstrip('/')}/services/oauth2/token", body


def _sf_token_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "identity",
    }


async def _sf_identity_label(http_client: Any, settings: Settings, token_payload: dict[str, Any]) -> str:
    identity_url = token_payload.get("id")
    access_token = token_payload.get("access_token")
    if not identity_url or not access_token:
        return ""
    try:
        ident = await http_client.request(
            "GET",
            identity_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept-Encoding": "identity"},
            timeout=15.0,
        )
        if ident.status_code == 200:
            return str(ident.json().get("username", "")).strip()
    except Exception:  # pragma: no cover - must not break connect
        pass
    return ""


def _sf_credential_data(
    settings: Settings,
    token_payload: dict[str, Any],
    login_url: str,
    label: str = "",
    client_id: str = "",
    client_secret: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    import time
    expires_in = token_payload.get("expires_in") or 7200
    try:
        exp_at = time.time() + float(expires_in)
    except Exception:
        exp_at = time.time() + 7200
    cid = (client_id or kwargs.get("client_id") or "").strip()
    csec = (client_secret or kwargs.get("client_secret") or "").strip()
    has_custom = kwargs.get("has_custom_credentials", False)
    if not has_custom:
        cid = ""
        csec = ""
    return {
        "instance_url": str(token_payload.get("instance_url", "")).rstrip("/"),
        "login_url": login_url,
        "access_token": token_payload.get("access_token", ""),
        "expires_at": exp_at,
        "refresh_token": token_payload["refresh_token"],
        "username": label,
        "user_id_url": str(token_payload.get("id", "")).strip(),
        "oauth": True,
        "api_version": settings.salesforce_api_version,
        "client_id": cid,
        "client_secret": csec,
    }


async def _sf_revoke_token(http_client: Any, settings: Settings, credential_data: dict[str, Any]) -> bool:
    """Revoke refresh/access token with Salesforce upstream revocation endpoint."""
    from urllib.parse import urlencode

    token = credential_data.get("refresh_token") or credential_data.get("access_token") or ""
    if not token:
        return True

    candidates = []
    if credential_data.get("instance_url"):
        candidates.append(str(credential_data["instance_url"]).rstrip("/"))
    if credential_data.get("login_url"):
        candidates.append(str(credential_data["login_url"]).rstrip("/"))
    if settings.salesforce_login_url:
        candidates.append(settings.salesforce_login_url.rstrip("/"))
    candidates.append("https://login.salesforce.com")

    urls = list(dict.fromkeys(candidates))
    success = False
    for base in urls:
        revoke_url = f"{base}/services/oauth2/revoke"
        body = urlencode({"token": token})
        try:
            resp = await http_client.request(
                "POST",
                revoke_url,
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept-Encoding": "identity",
                },
                timeout=15.0,
            )
            if resp.status_code in (200, 204):
                success = True
                break
        except Exception:
            continue
    return success


SALESFORCE = OAuthProviderSpec(
    key="salesforce",
    display_name="Salesforce",
    credential_type="salesforce",
    audit_connected="salesforce.connect",
    audit_failed="salesforce.connect_failed",
    marker_ok="salesforce_connected",
    marker_failed="salesforce_connect_failed",
    scopes_setting="salesforce_scopes",
    supports_pkce=True,
    uses_login_url=True,
    authorize_url=_sf_authorize_url,
    token_request=_sf_token_request,
    token_headers=_sf_token_headers,
    identity_label=_sf_identity_label,
    credential_data=_sf_credential_data,
    revoke_token=_sf_revoke_token,
)


# ----------------------------------------------------------------------
# HubSpot (Phase 33): standard authorization-code flow, no PKCE needed
# for confidential apps; tokens via /oauth/v1/token.
# ----------------------------------------------------------------------

HUBSPOT_AUTHORIZE_BASE = "https://app.hubspot.com/oauth/authorize"


def _hs_authorize_url(
    settings: Settings,
    *,
    state: str,
    challenge: str,
    login_url: str,
    prompt: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    db: Any = None,
    user_id: int | None = None,
    **kwargs: Any,
) -> str:
    from urllib.parse import urlencode

    cid = client_id
    r_uri = redirect_uri
    if not cid or not r_uri:
        resolved_cid, _secret, resolved_r_uri = HUBSPOT.server_config(
            settings, db=db, user_id=user_id, client_id=client_id, redirect_uri=redirect_uri
        )
        cid = cid or resolved_cid
        r_uri = r_uri or resolved_r_uri

    return (
        f"{HUBSPOT_AUTHORIZE_BASE}?"
        + urlencode({
            "client_id": cid,
            "redirect_uri": r_uri,
            "scope": HUBSPOT.scopes(settings),
            "state": state,
        })
    )


def _hs_token_request(
    settings: Settings,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
    login_url: str,
    client_id: str = "",
    client_secret: str = "",
    db: Any = None,
    user_id: int | None = None,
    **kwargs: Any,
) -> tuple[str, str]:
    from urllib.parse import urlencode

    cid = (client_id or "").strip() or settings.hubspot_client_id
    csec = (client_secret or "").strip() or settings.hubspot_client_secret
    if not cid or not csec:
        try:
            cid_sc, csec_sc, _ = HUBSPOT.server_config(
                settings, db=db, user_id=user_id, client_id=client_id, client_secret=client_secret
            )
            cid = cid or cid_sc
            csec = csec or csec_sc
        except Exception:
            pass

    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": cid,
        "client_secret": csec,
    })
    return "https://api.hubapi.com/oauth/v1/token", body


def _hs_token_headers() -> dict[str, str]:
    return {"Content-Type": "application/x-www-form-urlencoded"}


async def _hs_identity_label(http_client: Any, settings: Settings, token_payload: dict[str, Any]) -> str:
    access_token = token_payload.get("access_token") or ""
    if not access_token:
        return ""
    try:
        ident = await http_client.get(
            "https://api.hubapi.com/oauth/v1/access-tokens/" + access_token,
            headers={"Accept-Encoding": "identity"},
            timeout=15.0,
        )
        if ident.status_code == 200:
            data = ident.json()
            user = str(data.get("user", "")).strip()
            hub_id = str(data.get("hub_id", "")).strip()
            return user or (f"portal {hub_id}" if hub_id else "")
    except Exception:  # pragma: no cover - must not break connect
        pass
    return ""


def _hs_credential_data(settings: Settings, token_payload: dict[str, Any], login_url: str, label: str = "") -> dict[str, Any]:
    return {
        "hub_id": str(token_payload.get("hub_id", "") or ""),
        "user": label,
        "refresh_token": token_payload["refresh_token"],
        "private_token": "",
        "oauth": True,
    }


HUBSPOT = OAuthProviderSpec(
    key="hubspot",
    display_name="HubSpot",
    credential_type="hubspot",
    audit_connected="oauth.connected",
    audit_failed="oauth.connect_failed",
    marker_ok="oauth_connected",
    marker_failed="oauth_connect_failed",
    scopes_setting="hubspot_scopes",
    supports_pkce=False,
    uses_login_url=False,
    authorize_url=_hs_authorize_url,
    token_request=_hs_token_request,
    token_headers=_hs_token_headers,
    identity_label=_hs_identity_label,
    credential_data=_hs_credential_data,
)


# ----------------------------------------------------------------------
# Google Calendar (Phase 37): authorization-code with forced offline
# access so a refresh token is always minted; identity comes from the
# id_token JWT, decoded locally (no extra network call).
# ----------------------------------------------------------------------

GOOGLE_AUTHORIZE_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _google_authorize_url_factory(provider_key: str, config_prefix: str, scopes_setting: str, display_name: str):
    """Build an authorize-URL callable bound to one provider's config.

    Each Google-flavoured connector (Calendar / Sheets / Gmail / Drive)
    shares the same OAuth app but MUST request its own scope set on the
    consent screen — a shared closure over one spec would silently mint
    refresh tokens with the wrong scopes.
    """

    def _authorize(
        settings: Settings,
        *,
        state: str,
        challenge: str,
        login_url: str,
        prompt: str = "",
        client_id: str = "",
        redirect_uri: str = "",
        db: Any = None,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> str:
        from urllib.parse import urlencode

        cid = (client_id or "").strip()
        r_uri = (redirect_uri or "").strip()
        csecret = ""
        if not cid or not r_uri:
            try:
                spec = get_provider(provider_key)
                sc_cid, sc_sec, sc_r_uri = spec.server_config(
                    settings, db=db, user_id=user_id, client_id=client_id, redirect_uri=redirect_uri
                )
                cid = cid or sc_cid
                csecret = sc_sec
                r_uri = r_uri or sc_r_uri
            except Exception:
                pass

        cid = cid or getattr(settings, f"{config_prefix}_client_id", "")
        csecret = csecret or getattr(settings, f"{config_prefix}_client_secret", "")
        if not r_uri:
            r_uri = getattr(settings, f"{config_prefix}_redirect_uri", "")
            if not r_uri:
                base = (getattr(settings, "public_url", "") or "").rstrip("/")
                if base:
                    r_uri = f"{base}/api/auth/{provider_key}/callback"
                else:
                    r_uri = f"https://flowsmith.dev.idslogic.net/api/auth/{provider_key}/callback"
        if not cid or not r_uri:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{display_name} OAuth is not configured on the server or in database.",
            )
        return (
            f"{GOOGLE_AUTHORIZE_BASE}?"
            + urlencode({
                "client_id": cid,
                "redirect_uri": r_uri,
                "response_type": "code",
                "scope": getattr(settings, scopes_setting, ""),
                "state": state,
                # Force a refresh token on every connect (Google otherwise
                # issues one only on first consent).
                "access_type": "offline",
                "prompt": prompt if prompt else "consent",
            })
        )

    return _authorize


def _google_token_request_factory(config_prefix: str, provider_key: str = "google"):
    def _token_request(
        settings: Settings,
        *,
        code: str,
        verifier: str,
        redirect_uri: str,
        login_url: str,
        client_id: str = "",
        client_secret: str = "",
        db: Any = None,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> tuple[str, str]:
        from urllib.parse import urlencode

        cid = (client_id or "").strip()
        csec = (client_secret or "").strip()
        if not cid or not csec:
            try:
                spec = get_provider(provider_key)
                sc_cid, sc_sec, _ = spec.server_config(
                    settings, db=db, user_id=user_id, client_id=client_id, client_secret=client_secret
                )
                cid = cid or sc_cid
                csec = csec or sc_sec
            except Exception:
                pass
        cid = cid or getattr(settings, f"{config_prefix}_client_id", "")
        csec = csec or getattr(settings, f"{config_prefix}_client_secret", "")
        body = urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": cid,
            "client_secret": csec,
        })
        return GOOGLE_TOKEN_URL, body

    return _token_request


def _google_token_headers() -> dict[str, str]:
    return {"Content-Type": "application/x-www-form-urlencoded"}


async def _google_identity_label(http_client: Any, settings: Settings, token_payload: dict[str, Any]) -> str:
    """Decode the id_token JWT payload locally. No signature check: the
    token arrived directly from Google over TLS inside the exchange."""
    id_token = token_payload.get("id_token") or ""
    if not id_token or id_token.count(".") < 2:
        return ""
    import base64
    import json as _json

    try:
        part = id_token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claims = _json.loads(base64.urlsafe_b64decode(part.encode()))
        return str(claims.get("email", "")).strip()
    except Exception:  # pragma: no cover - cosmetic
        return ""


def _google_credential_data(settings: Settings, token_payload: dict[str, Any], login_url: str, label: str = "") -> dict[str, Any]:
    return {
        "user": label,
        "refresh_token": token_payload["refresh_token"],
        "oauth": True,
    }


async def _google_revoke_token(http_client: Any, settings: Settings, credential_data: dict[str, Any]) -> bool:
    """Revoke refresh/access token with Google upstream revocation endpoint."""
    from urllib.parse import urlencode

    token = credential_data.get("refresh_token") or credential_data.get("access_token") or ""
    if not token:
        return True

    revoke_url = "https://oauth2.googleapis.com/revoke"
    body = urlencode({"token": token})
    try:
        resp = await http_client.request(
            "POST",
            revoke_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15.0,
        )
        return resp.status_code in (200, 204)
    except Exception:
        return False


GOOGLE = OAuthProviderSpec(
    key="google_calendar",
    display_name="Google Calendar",
    credential_type="google_calendar",
    audit_connected="oauth.connected",
    audit_failed="oauth.connect_failed",
    marker_ok="oauth_connected",
    marker_failed="oauth_connect_failed",
    scopes_setting="google_scopes",
    config_prefix="google",
    supports_pkce=False,
    uses_login_url=False,
    authorize_url=_google_authorize_url_factory("google_calendar", "google", "google_scopes", "Google Calendar"),
    token_request=_google_token_request_factory("google"),
    token_headers=_google_token_headers,
    identity_label=_google_identity_label,
    credential_data=_google_credential_data,
    revoke_token=_google_revoke_token,
)


# ----------------------------------------------------------------------
# Google Sheets (Phase 39): same Google OAuth app as Calendar
# (config_prefix=google), different scope set + credential type.
# ----------------------------------------------------------------------

GOOGLE_SHEETS = OAuthProviderSpec(
    key="google_sheets",
    display_name="Google Sheets",
    credential_type="google_sheets",
    audit_connected="oauth.connected",
    audit_failed="oauth.connect_failed",
    marker_ok="oauth_connected",
    marker_failed="oauth_connect_failed",
    scopes_setting="google_sheets_scopes",
    config_prefix="google",
    supports_pkce=False,
    uses_login_url=False,
    authorize_url=_google_authorize_url_factory("google_sheets", "google", "google_sheets_scopes", "Google Sheets"),
    token_request=_google_token_request_factory("google"),
    token_headers=_google_token_headers,
    identity_label=_google_identity_label,
    credential_data=_google_credential_data,
    revoke_token=_google_revoke_token,
)


# ----------------------------------------------------------------------
# Gmail (Phase 41): same Google OAuth app; send-only scope.
# ----------------------------------------------------------------------

GMAIL = OAuthProviderSpec(
    key="gmail",
    display_name="Gmail",
    credential_type="gmail",
    audit_connected="oauth.connected",
    audit_failed="oauth.connect_failed",
    marker_ok="oauth_connected",
    marker_failed="oauth_connect_failed",
    scopes_setting="gmail_scopes",
    config_prefix="google",
    supports_pkce=False,
    uses_login_url=False,
    authorize_url=_google_authorize_url_factory("gmail", "google", "gmail_scopes", "Gmail"),
    token_request=_google_token_request_factory("google"),
    token_headers=_google_token_headers,
    identity_label=_google_identity_label,
    credential_data=_google_credential_data,
    revoke_token=_google_revoke_token,
)


# ----------------------------------------------------------------------
# Google Drive (Phase 11 business connectors): same Google OAuth app as
# Calendar/Sheets/Gmail with the Drive scope set.
# ----------------------------------------------------------------------

GOOGLE_DRIVE = OAuthProviderSpec(
    key="google_drive",
    display_name="Google Drive",
    credential_type="google_drive",
    audit_connected="oauth.connected",
    audit_failed="oauth.connect_failed",
    marker_ok="oauth_connected",
    marker_failed="oauth_connect_failed",
    scopes_setting="google_drive_scopes",
    config_prefix="google",
    supports_pkce=False,
    uses_login_url=False,
    authorize_url=_google_authorize_url_factory("google_drive", "google", "google_drive_scopes", "Google Drive"),
    token_request=_google_token_request_factory("google"),
    token_headers=_google_token_headers,
    identity_label=_google_identity_label,
    credential_data=_google_credential_data,
    revoke_token=_google_revoke_token,
)


# ----------------------------------------------------------------------
# Google Docs: same Google OAuth app as Calendar/Sheets/Gmail/Drive
# with the documents scope set.
# ----------------------------------------------------------------------

GOOGLE_DOCS = OAuthProviderSpec(
    key="google_docs",
    display_name="Google Docs",
    credential_type="google_docs",
    audit_connected="oauth.connected",
    audit_failed="oauth.connect_failed",
    marker_ok="oauth_connected",
    marker_failed="oauth_connect_failed",
    scopes_setting="google_docs_scopes",
    config_prefix="google",
    supports_pkce=False,
    uses_login_url=False,
    authorize_url=_google_authorize_url_factory("google_docs", "google", "google_docs_scopes", "Google Docs"),
    token_request=_google_token_request_factory("google"),
    token_headers=_google_token_headers,
    identity_label=_google_identity_label,
    credential_data=_google_credential_data,
    revoke_token=_google_revoke_token,
)


# ----------------------------------------------------------------------
# Microsoft Dynamics 365 CRM (Dataverse)
# Authenticates via Microsoft Entra ID (Azure AD) OAuth 2.0 endpoints.
# Supports multi-tenant (common) and single-tenant endpoints,
# PKCE verification, and instance_url binding.
# ----------------------------------------------------------------------

def _dynamics_normalize_urls(login_url: str, settings: Settings) -> tuple[str, str]:
    """Extract (tenant_id, instance_url) from user-supplied login_url or settings."""
    tenant = (getattr(settings, "dynamics_crm_tenant_id", "") or "common").strip()
    instance_url = (getattr(settings, "dynamics_crm_instance_url", "") or "").strip().rstrip("/")

    url = (login_url or "").strip()
    if url:
        if "login.microsoftonline.com" in url:
            parts = url.rstrip("/").split("/")
            if len(parts) >= 4 and parts[3] and parts[3] != "oauth2":
                tenant = parts[3]
        elif url.startswith("http://") or url.startswith("https://"):
            instance_url = url.rstrip("/")
        elif "." in url:
            instance_url = f"https://{url.rstrip('/')}"
        else:
            tenant = url

    return tenant, instance_url


def _dynamics_authorize_url(
    settings: Settings,
    *,
    state: str,
    challenge: str,
    login_url: str,
    prompt: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    db: Any = None,
    user_id: int | None = None,
    **kwargs: Any,
) -> str:
    from urllib.parse import urlencode

    cid = client_id
    r_uri = redirect_uri
    if not cid or not r_uri:
        resolved_cid, _secret, resolved_r_uri = DYNAMICS_CRM.server_config(
            settings, db=db, user_id=user_id, client_id=client_id, redirect_uri=redirect_uri
        )
        cid = cid or resolved_cid
        r_uri = r_uri or resolved_r_uri

    tenant, instance_url = _dynamics_normalize_urls(login_url, settings)

    if instance_url:
        scope = f"{instance_url}/.default offline_access"
    else:
        scope = DYNAMICS_CRM.scopes(settings)

    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": r_uri,
        "response_mode": "query",
        "scope": scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if prompt:
        params["prompt"] = prompt

    auth_endpoint = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    return f"{auth_endpoint}?{urlencode(params)}"


def _dynamics_token_request(
    settings: Settings,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
    login_url: str,
    client_id: str = "",
    client_secret: str = "",
    db: Any = None,
    user_id: int | None = None,
    **kwargs: Any,
) -> tuple[str, str]:
    from urllib.parse import urlencode

    cid = (client_id or "").strip() or getattr(settings, "dynamics_crm_client_id", "")
    csec = (client_secret or "").strip() or getattr(settings, "dynamics_crm_client_secret", "")
    if not cid or not csec:
        try:
            cid_sc, csec_sc, _ = DYNAMICS_CRM.server_config(
                settings, db=db, user_id=user_id, client_id=client_id, client_secret=client_secret
            )
            cid = cid or cid_sc
            csec = csec or csec_sc
        except Exception:
            pass

    tenant, _ = _dynamics_normalize_urls(login_url, settings)
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    body_params = {
        "client_id": cid,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier or "",
    }
    if csec:
        body_params["client_secret"] = csec

    return token_url, urlencode(body_params)


def _dynamics_token_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "identity",
    }


async def _dynamics_identity_label(http_client: Any, settings: Settings, token_payload: dict[str, Any]) -> str:
    access_token = token_payload.get("access_token") or ""
    if not access_token:
        return ""

    instance_url = str(token_payload.get("instance_url") or getattr(settings, "dynamics_crm_instance_url", "")).rstrip("/")
    if instance_url:
        try:
            resp = await http_client.request(
                "GET",
                f"{instance_url}/api/data/v9.2/WhoAmI",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                    "OData-Version": "4.0",
                },
                timeout=15.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return str(data.get("UserId") or data.get("BusinessUnitId") or "").strip()
        except Exception:
            pass

    try:
        resp = await http_client.request(
            "GET",
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            user_data = resp.json()
            return str(user_data.get("userPrincipalName") or user_data.get("displayName") or "").strip()
    except Exception:
        pass

    return ""


def _dynamics_credential_data(
    settings: Settings,
    token_payload: dict[str, Any],
    login_url: str,
    label: str = "",
    client_id: str = "",
    client_secret: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    import time

    tenant, instance_url = _dynamics_normalize_urls(login_url, settings)
    cid = (client_id or kwargs.get("client_id") or "").strip()
    csec = (client_secret or kwargs.get("client_secret") or "").strip()
    has_custom = kwargs.get("has_custom_credentials", False)
    if not has_custom:
        cid = ""
        csec = ""

    expires_in = token_payload.get("expires_in") or 3600
    try:
        exp_at = time.time() + float(expires_in)
    except Exception:
        exp_at = time.time() + 3600

    return {
        "instance_url": instance_url or str(token_payload.get("instance_url", "")).rstrip("/"),
        "auth_type": "oauth2",
        "tenant_id": tenant,
        "access_token": token_payload.get("access_token", ""),
        "refresh_token": token_payload.get("refresh_token", ""),
        "expires_at": exp_at,
        "username": label,
        "user": label,
        "oauth": True,
        "client_id": cid,
        "client_secret": csec,
    }


async def _dynamics_revoke_token(http_client: Any, settings: Settings, credential_data: dict[str, Any]) -> bool:
    return True


DYNAMICS_CRM = OAuthProviderSpec(
    key="dynamics_crm",
    display_name="Microsoft Dynamics 365",
    credential_type="dynamics_crm",
    audit_connected="dynamics_crm.connected",
    audit_failed="dynamics_crm.connect_failed",
    marker_ok="dynamics_crm_connected",
    marker_failed="dynamics_crm_connect_failed",
    scopes_setting="dynamics_crm_scopes",
    config_prefix="dynamics_crm",
    supports_pkce=True,
    uses_login_url=True,
    authorize_url=_dynamics_authorize_url,
    token_request=_dynamics_token_request,
    token_headers=_dynamics_token_headers,
    identity_label=_dynamics_identity_label,
    credential_data=_dynamics_credential_data,
    revoke_token=_dynamics_revoke_token,
)


PROVIDERS: dict[str, OAuthProviderSpec] = {
    SALESFORCE.key: SALESFORCE,
    HUBSPOT.key: HUBSPOT,
    DYNAMICS_CRM.key: DYNAMICS_CRM,
    GOOGLE.key: GOOGLE,
    "google": GOOGLE,
    GOOGLE_SHEETS.key: GOOGLE_SHEETS,
    GMAIL.key: GMAIL,
    GOOGLE_DRIVE.key: GOOGLE_DRIVE,
    GOOGLE_DOCS.key: GOOGLE_DOCS,
}


def get_provider(key: str) -> OAuthProviderSpec:
    spec = PROVIDERS.get(key)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown OAuth provider '{key}'.")
    return spec


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) pair (RFC 7636, S256)."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def purge_stale_states(db: Session) -> None:
    """Opportunistically delete expired, unused authorize states."""
    try:
        from datetime import UTC, datetime, timedelta

        ttl = get_settings().oauth_state_ttl_seconds
        cutoff = datetime.now(UTC) - timedelta(seconds=ttl)
        stale = db.scalars(select(OAuthState).where(OAuthState.created_at < cutoff)).all()
        for row in stale:
            db.delete(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.debug("purge_stale_states failed: %s", exc)


def get_existing_oauth_credential(
    db: Session,
    user: User,
    cred_type: str,
    account_data: dict[str, Any] | None = None,
) -> credential_service.Credential | None:
    """Find an existing active OAuth connection for user+type.

    If account_data is provided, matches specifically against that account's
    identity so distinct accounts (e.g. multiple Salesforce accounts or orgs)
    coexist as separate credentials.
    """
    previous = db.scalars(
        select(credential_service.Credential).where(
            credential_service.Credential.user_id == user.id,
            credential_service.Credential.type == cred_type,
        ).order_by(credential_service.Credential.created_at.desc())
    ).all()

    candidates: list[tuple[credential_service.Credential, dict[str, Any]]] = []
    for rec in previous:
        try:
            raw = rec.data
            blob = decrypt_text(raw if isinstance(raw, bytes) else str(raw).encode())
            parsed = json.loads(blob)
            if parsed.get("oauth"):
                candidates.append((rec, parsed))
        except Exception:
            continue

    if not candidates:
        return None

    if not account_data:
        # Default fallback: return first candidate
        return candidates[0][0]

    # Account-specific identity matching:
    acc_id_url = str(account_data.get("user_id_url") or "").strip()
    acc_user = str(account_data.get("username") or account_data.get("user") or "").strip()
    acc_inst = str(account_data.get("instance_url") or "").strip().rstrip("/")
    acc_hub = str(account_data.get("hub_id") or "").strip()

    # 1. Match by canonical identity URL (Salesforce id)
    if acc_id_url:
        for rec, data in candidates:
            if str(data.get("user_id_url") or "").strip() == acc_id_url:
                return rec

    # 2. Match by username + instance_url
    if acc_user and acc_inst:
        for rec, data in candidates:
            cand_user = str(data.get("username") or data.get("user") or "").strip()
            cand_inst = str(data.get("instance_url") or "").strip().rstrip("/")
            if cand_user == acc_user and cand_inst == acc_inst:
                return rec

    # 3. Match by username / email alone (if set)
    if acc_user:
        for rec, data in candidates:
            cand_user = str(data.get("username") or data.get("user") or "").strip()
            if cand_user == acc_user:
                return rec

    # 4. Match by hub_id (HubSpot)
    if acc_hub:
        for rec, data in candidates:
            cand_hub = str(data.get("hub_id") or "").strip()
            if cand_hub == acc_hub:
                return rec

    # 5. Match by instance_url alone if no username exists on either side
    if acc_inst and not acc_user:
        for rec, data in candidates:
            cand_user = str(data.get("username") or data.get("user") or "").strip()
            cand_inst = str(data.get("instance_url") or "").strip().rstrip("/")
            if not cand_user and cand_inst == acc_inst:
                return rec

    # No existing record matched this account's identity -> It's a new account!
    return None


def replace_oauth_credential(
    db: Session,
    user: User,
    cred_type: str,
    keep_id: str | None = None,
    account_data: dict[str, Any] | None = None,
) -> None:
    """Optionally clean up duplicate credentials of the exact SAME account.

    Distinct accounts (e.g. multiple Salesforce orgs or users) are never deleted.
    """
    if not account_data or not keep_id:
        return
    previous = db.scalars(
        select(credential_service.Credential).where(
            credential_service.Credential.user_id == user.id,
            credential_service.Credential.type == cred_type,
        )
    ).all()
    for rec in previous:
        if rec.id == keep_id:
            continue
        try:
            raw = rec.data
            blob = decrypt_text(raw if isinstance(raw, bytes) else str(raw).encode())
            parsed = json.loads(blob)
            if not parsed.get("oauth"):
                continue
            match = get_existing_oauth_credential(db, user, cred_type, account_data=parsed)
            if match and match.id == keep_id:
                db.delete(rec)
        except Exception:
            continue



