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

    def server_config(self, settings: Settings) -> tuple[str, str, str]:
        """(client_id, client_secret, redirect_uri) or HTTP 422."""
        prefix = self.config_prefix or self.key
        cid = getattr(settings, f"{prefix}_client_id", "")
        csecret = getattr(settings, f"{prefix}_client_secret", "")
        redirect = getattr(settings, f"{prefix}_redirect_uri", "")
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
                f"{self.display_name} OAuth is not configured on the server "
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
    authorize_url: Callable[..., str] | None = None  # (settings, state, challenge, login_url) -> url
    token_request: Callable[..., tuple[str, str]] | None = None  # (settings, code, verifier, redirect_uri, login_url) -> (url, body)
    token_headers: Callable[[], dict[str, str]] | None = None  # () -> extra headers
    identity_label: Callable[..., Any] | None = None  # async (http_client, settings, token_payload) -> label
    credential_data: Callable[..., dict[str, Any]] | None = None  # (settings, token_payload, login_url, label) -> blob


def _sf_authorize_url(settings: Settings, *, state: str, challenge: str, login_url: str) -> str:
    from urllib.parse import urlencode

    cid, _secret, redirect_uri = SALESFORCE.server_config(settings)
    return (
        f"{login_url.rstrip('/')}/services/oauth2/authorize?"
        + urlencode({
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "scope": SALESFORCE.scopes(settings),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
    )


def _sf_token_request(
    settings: Settings, *, code: str, verifier: str, redirect_uri: str, login_url: str
) -> tuple[str, str]:
    from urllib.parse import urlencode

    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.salesforce_client_id,
        "client_secret": settings.salesforce_client_secret,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier or "",
    })
    return f"{login_url.rstrip('/')}/services/oauth2/token", body


def _sf_token_headers() -> dict[str, str]:
    # The body is a PRE-ENCODED form string, so httpx will not set a
    # content type for us — without this header Salesforce answers
    # unsupported_grant_type. Accept-Encoding identity: Salesforce (F5
    # edge) can return a corrupt gzip body, and authorization codes are
    # single-use so the exchange must never need a retry.
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "identity",
    }


async def _sf_identity_label(http_client: Any, settings: Settings, token_payload: dict[str, Any]) -> str:
    """Best-effort identity lookup; cosmetic only."""
    access_token = token_payload.get("access_token") or ""
    identity_url = token_payload.get("id") or ""
    if not access_token or not identity_url:
        return ""
    try:
        ident = await http_client.get(
            identity_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept-Encoding": "identity"},
            timeout=15.0,
        )
        if ident.status_code == 200:
            return str(ident.json().get("username", "")).strip()
    except Exception:  # pragma: no cover - must not break connect
        pass
    return ""


def _sf_credential_data(settings: Settings, token_payload: dict[str, Any], login_url: str, label: str = "") -> dict[str, Any]:
    import time
    expires_in = token_payload.get("expires_in") or 7200
    try:
        exp_at = time.time() + float(expires_in)
    except Exception:
        exp_at = time.time() + 7200
    return {
        "instance_url": str(token_payload.get("instance_url", "")).rstrip("/"),
        "login_url": login_url,
        "access_token": token_payload.get("access_token", ""),
        "expires_at": exp_at,
        "refresh_token": token_payload["refresh_token"],
        "username": label,
        "oauth": True,
        "api_version": settings.salesforce_api_version,
        "client_id": "",
        "client_secret": "",
    }


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
)


# ----------------------------------------------------------------------
# HubSpot (Phase 33): standard authorization-code flow, no PKCE needed
# for confidential apps; tokens via /oauth/v1/token.
# ----------------------------------------------------------------------

HUBSPOT_AUTHORIZE_BASE = "https://app.hubspot.com/oauth/authorize"


def _hs_authorize_url(settings: Settings, *, state: str, challenge: str, login_url: str) -> str:
    from urllib.parse import urlencode

    cid, _secret, redirect_uri = HUBSPOT.server_config(settings)
    return (
        f"{HUBSPOT_AUTHORIZE_BASE}?"
        + urlencode({
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "scope": HUBSPOT.scopes(settings),
            "state": state,
        })
    )


def _hs_token_request(
    settings: Settings, *, code: str, verifier: str, redirect_uri: str, login_url: str
) -> tuple[str, str]:
    from urllib.parse import urlencode

    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.hubspot_client_id,
        "client_secret": settings.hubspot_client_secret,
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

    def _authorize(settings: Settings, *, state: str, challenge: str, login_url: str) -> str:
        from urllib.parse import urlencode

        cid = getattr(settings, f"{config_prefix}_client_id", "")
        csecret = getattr(settings, f"{config_prefix}_client_secret", "")
        redirect_uri = getattr(settings, f"{config_prefix}_redirect_uri", "")
        if not redirect_uri:
            base = (getattr(settings, "public_url", "") or "").rstrip("/")
            if base:
                redirect_uri = f"{base}/api/auth/{provider_key}/callback"
        if not cid or not csecret or not redirect_uri:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{display_name} OAuth is not configured on the server.",
            )
        return (
            f"{GOOGLE_AUTHORIZE_BASE}?"
            + urlencode({
                "client_id": cid,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": getattr(settings, scopes_setting, ""),
                "state": state,
                # Force a refresh token on every connect (Google otherwise
                # issues one only on first consent).
                "access_type": "offline",
                "prompt": "consent",
            })
        )

    return _authorize


def _google_token_request_factory(config_prefix: str):
    def _token_request(
        settings: Settings, *, code: str, verifier: str, redirect_uri: str, login_url: str
    ) -> tuple[str, str]:
        from urllib.parse import urlencode

        body = urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": getattr(settings, f"{config_prefix}_client_id", ""),
            "client_secret": getattr(settings, f"{config_prefix}_client_secret", ""),
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
)


PROVIDERS: dict[str, OAuthProviderSpec] = {
    SALESFORCE.key: SALESFORCE,
    HUBSPOT.key: HUBSPOT,
    GOOGLE.key: GOOGLE,
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
    from datetime import UTC, datetime, timedelta

    ttl = get_settings().oauth_state_ttl_seconds
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl)
    stale = db.scalars(select(OAuthState).where(OAuthState.created_at < cutoff)).all()
    for row in stale:
        db.delete(row)
    db.commit()


def get_existing_oauth_credential(db: Session, user: User, cred_type: str) -> credential_service.Credential | None:
    """Find an existing active OAuth connection for user+type to reuse its ID across reconnects."""
    previous = db.scalars(
        select(credential_service.Credential).where(
            credential_service.Credential.user_id == user.id,
            credential_service.Credential.type == cred_type,
        )
    ).all()
    for rec in previous:
        try:
            raw = rec.data
            blob = decrypt_text(raw if isinstance(raw, bytes) else str(raw).encode())
            if json.loads(blob).get("oauth"):
                return rec
        except Exception:
            continue
    return None


def replace_oauth_credential(db: Session, user: User, cred_type: str, keep_id: str | None = None) -> None:
    """Keep a single active OAuth connection per user+type: delete any
    previous OAuth-created credential of this type (manual ones stay),
    optionally preserving keep_id."""
    previous = db.scalars(
        select(credential_service.Credential).where(
            credential_service.Credential.user_id == user.id,
            credential_service.Credential.type == cred_type,
        )
    ).all()
    for rec in previous:
        if keep_id and rec.id == keep_id:
            continue
        try:
            raw = rec.data
            blob = decrypt_text(raw if isinstance(raw, bytes) else str(raw).encode())
            if json.loads(blob).get("oauth"):
                db.delete(rec)
        except Exception:
            continue


