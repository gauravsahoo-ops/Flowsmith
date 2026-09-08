"""OAuth Token Manager — reusable OAuth2 engine (spec).

Supports authorization URL, token URL, client id/secret, scopes,
access token, refresh token, expiration, automatic refresh, rotation,
and connection testing. Provider-specific configs extend this engine.
"""
from __future__ import annotations

import time
import json
from typing import Any, Dict

import httpx

from app.security.crypto import decrypt_text, encrypt_text  # noqa
from app.models.credential import Credential
from sqlalchemy.orm import Session


class OAuthManager:
    """Generic OAuth2 manager. Storage is via CredentialStore (encrypted)."""

    def __init__(self, http_client: Any = None) -> None:
        self.http_client = http_client

    async def get_valid_token(self, cred_data: Dict[str, Any], force_refresh: bool = False) -> Dict[str, Any]:
        """Return cred_data with valid access_token, refreshing if expired."""
        if not self.is_expired(cred_data) and not force_refresh and cred_data.get("access_token"):
            return cred_data
        if not cred_data.get("refresh_token"):
            raise ValueError("OAuth2 refresh token missing")
        return await self.refresh(cred_data)

    def is_expired(self, cred_data: Dict[str, Any]) -> bool:
        exp = cred_data.get("expires_at") or 0
        try:
            exp_f = float(exp)
        except Exception:
            return False
        if not exp_f:
            return False
        return time.time() >= (exp_f - 60)

    async def refresh(self, cred_data: Dict[str, Any]) -> Dict[str, Any]:
        token_url = cred_data.get("token_url")
        client_id = cred_data.get("client_id")
        client_secret = cred_data.get("client_secret")
        refresh_token = cred_data.get("refresh_token")
        if not token_url or not client_id or not client_secret or not refresh_token:
            raise ValueError("OAuth2 refresh requires token_url, client_id, client_secret, refresh_token")
        client = self.http_client or httpx.AsyncClient()
        close = self.http_client is None
        try:
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15.0,
            )
            if resp.status_code != 200:
                raise ValueError(f"Token refresh failed {resp.status_code}: {resp.text[:200]}")
            payload = resp.json()
            new_data = dict(cred_data)
            new_data["access_token"] = payload.get("access_token", cred_data.get("access_token"))
            if payload.get("refresh_token"):
                new_data["refresh_token"] = payload["refresh_token"]  # rotation
            expires_in = payload.get("expires_in")
            if expires_in:
                try:
                    new_data["expires_at"] = time.time() + float(expires_in)
                except Exception:
                    pass

            # Persist fresh access token and rotated refresh token to database
            if cred_data.get("_credential_id"):
                try:
                    import json
                    from app.db import get_session
                    from app.models.credential import Credential
                    from app.security.crypto import encrypt_text, decrypt_text
                    with get_session() as db_sess:
                        c_rec = db_sess.get(Credential, cred_data["_credential_id"])
                        if c_rec:
                            c_dict = json.loads(decrypt_text(c_rec.data))
                            c_dict["access_token"] = new_data["access_token"]
                            if new_data.get("expires_at"):
                                c_dict["expires_at"] = new_data["expires_at"]
                            if payload.get("refresh_token"):
                                c_dict["refresh_token"] = payload["refresh_token"]
                            c_rec.data = encrypt_text(json.dumps(c_dict))
                            db_sess.commit()
                except Exception:
                    pass

            return new_data
        finally:
            if close:
                await client.aclose()

    async def test_connection(self, cred_data: Dict[str, Any], test_url: str | None = None) -> Dict[str, Any]:
        """Probe OAuth token validity via a test request if test_url provided."""
        token = cred_data.get("access_token")
        if not token:
            return {"ok": False, "message": "No access token"}
        if not test_url:
            # Validate not expired
            if self.is_expired(cred_data):
                return {"ok": False, "message": "Token expired"}
            return {"ok": True, "message": "Token present and not expired."}
        client = self.http_client or httpx.AsyncClient()
        close = self.http_client is None
        try:
            resp = await client.get(test_url, headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
            if resp.status_code < 400:
                return {"ok": True, "message": f"Test request succeeded {resp.status_code}"}
            return {"ok": False, "message": f"Test request failed {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}
        finally:
            if close:
                await client.aclose()

    def persist_refresh(self, db: Session, credential_id: str, new_data: Dict[str, Any]) -> None:
        """Persist refreshed tokens back to store."""
        from app.db import get_session
        rec = db.get(Credential, credential_id)
        if rec is None:
            return
        rec.data = encrypt_text(json.dumps(new_data))
        db.commit()


_oauth_manager = OAuthManager()


def get_oauth_manager() -> OAuthManager:
    return _oauth_manager
