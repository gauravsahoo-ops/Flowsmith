"""Salesforce authentication provider for HTTP Request node.

Allows HTTP Request nodes using Predefined Credential Type 'Salesforce OAuth2 API'
to resolve the Salesforce access token and inject 'Authorization: Bearer <token>'.
"""
from __future__ import annotations

from typing import Any, Dict
from .base import AuthProvider


class SalesforceAuthProvider(AuthProvider):
    provider_id = "salesforce"
    display_name = "Salesforce OAuth2 API"
    auth_type = "oauth2"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "access_token": str(data.get("access_token", "") or data.get("accessToken", "") or data.get("token", "")).strip(),
            "refresh_token": str(data.get("refresh_token", "") or data.get("refreshToken", "")).strip(),
            "instance_url": str(data.get("instance_url", "") or data.get("login_url", "")).strip(),
            "client_id": str(data.get("client_id", "")).strip(),
            "client_secret": str(data.get("client_secret", "")).strip(),
        }

    def validateCredential(self, data: Dict[str, Any]) -> None:
        has_oauth = bool(data.get("access_token") or data.get("refresh_token"))
        has_userpass = bool(data.get("username") and data.get("password"))
        if not has_oauth and not has_userpass:
            raise ValueError("Salesforce credential requires an access_token, refresh_token, or username and password.")

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        resolved = self.resolveCredential(cred)
        token = resolved.get("access_token")
        if not token:
            raise ValueError("Salesforce access token missing. Please reconnect your Salesforce credential.")
        headers = dict(request.get("headers") or {})
        headers.setdefault("Authorization", f"Bearer {token}")
        request["headers"] = headers
        return request

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(data)
        for k in ("client_secret", "access_token", "refresh_token", "password"):
            if out.get(k):
                out[k] = "••••••••"
        return out

    async def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            from app.connectors import get_registry
            sf_conn = get_registry().get("salesforce")
            if sf_conn and hasattr(sf_conn, "test_connection"):
                res = await sf_conn.test_connection(cred)
                return res
            if cred.get("access_token") or cred.get("refresh_token"):
                return {"ok": True, "message": "Salesforce OAuth credentials present."}
            return {"ok": True, "message": "Salesforce credentials configured."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
