"""Bearer Auth provider."""
from __future__ import annotations

from typing import Any, Dict

from .base import AuthProvider


class BearerAuthProvider(AuthProvider):
    provider_id = "bearer"
    display_name = "Bearer Auth"
    auth_type = "bearer"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        # Supports token or api_key field for backward compat with `http` type
        token = data.get("token") or data.get("api_key") or data.get("auth_token") or data.get("bearer_token") or ""
        return {"token": str(token).strip()}

    def validateCredential(self, data: Dict[str, Any]) -> None:
        cred = self.resolveCredential(data)
        if not cred["token"]:
            raise ValueError("Bearer Auth requires token.")

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        token = str(cred.get("token", "")).strip()
        if not token:
            raise ValueError("Bearer token missing")
        headers = dict(request.get("headers") or {})
        headers.setdefault("Authorization", f"Bearer {token}")
        request["headers"] = headers
        return request

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"token": "••••••••" if data.get("token") or data.get("api_key") else ""}

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            return {"ok": True, "message": "Bearer token present."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
