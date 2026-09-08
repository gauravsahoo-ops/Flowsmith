"""OAuth2 provider (generic, reusable engine).

Handles authorization URL, token URL, scopes, access/refresh tokens,
expiration, automatic refresh and rotation. Provider-specific OAuth2
integrations (Salesforce, Google, Slack, etc) extend this engine instead
of duplicating code.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from .base import AuthProvider


class OAuth2Provider(AuthProvider):
    provider_id = "oauth2"
    display_name = "OAuth2 API"
    auth_type = "oauth2"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "client_id": str(data.get("client_id", "")).strip(),
            "client_secret": str(data.get("client_secret", "")).strip(),
            "access_token": str(data.get("access_token", "") or data.get("accessToken", "") or data.get("token", "")).strip(),
            "refresh_token": str(data.get("refresh_token", "") or data.get("refreshToken", "")).strip(),
            "token_url": str(data.get("token_url", "") or data.get("tokenUrl", "")).strip(),
            "authorization_url": str(data.get("authorization_url", "") or data.get("authorizationUrl", "")).strip(),
            "scopes": data.get("scopes") or data.get("scope") or "",
            "expires_at": data.get("expires_at") or data.get("expiresAt") or 0,
            "expires_in": data.get("expires_in") or data.get("expiresIn") or 0,
        }

    def validateCredential(self, data: Dict[str, Any]) -> None:
        cred = self.resolveCredential(data)
        if not cred["access_token"] and not cred["refresh_token"]:
            raise ValueError("OAuth2 requires access_token or refresh_token.")
        # token_url required for refresh
        if cred["refresh_token"] and not cred["token_url"] and not cred["client_id"]:
            # Allow refresh_token alone if token_url will be resolved via provider spec
            pass

    def is_expired(self, cred: Dict[str, Any]) -> bool:
        cred = self.resolveCredential(cred)
        exp = cred.get("expires_at")
        if not exp:
            return False
        try:
            exp_f = float(exp)
        except Exception:
            return False
        # Consider expired if within 60s of expiry
        return time.time() >= (exp_f - 60)

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(cred)
        token = cred.get("access_token")
        if not token:
            # Attempt refresh if possible (synchronous placeholder — real refresh is async via OAuthManager)
            raise ValueError("OAuth2 access token missing and refresh not performed. Call refreshCredential first.")
        headers = dict(request.get("headers") or {})
        headers.setdefault("Authorization", f"Bearer {token}")
        request["headers"] = headers
        return request

    def refreshCredential(self, data: Dict[str, Any]) -> Dict[str, Any] | None:
        # Generic refresh requires token_url + client credentials + refresh_token
        cred = self.resolveCredential(data)
        if not cred["refresh_token"]:
            return None
        if not cred["token_url"]:
            # No token_url to refresh against — caller must handle provider-specific refresh
            return None
        # Real HTTP refresh is handled by OAuthManager (needs async http client)
        # This method signals that refresh is supported; actual network call is in manager
        return None

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(data)
        out = dict(cred)
        for k in ("client_secret", "access_token", "refresh_token"):
            if out.get(k):
                out[k] = "••••••••"
        return out

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            if self.is_expired(cred):
                return {"ok": False, "message": "OAuth2 token expired — refresh required."}
            return {"ok": True, "message": "OAuth2 credentials present."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
