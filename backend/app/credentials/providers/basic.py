"""Basic Auth provider."""
from __future__ import annotations

import base64
from typing import Any, Dict

from .base import AuthProvider


class BasicAuthProvider(AuthProvider):
    provider_id = "basic"
    display_name = "Basic Auth"
    auth_type = "basic"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"username": str(data.get("username", "")).strip(), "password": str(data.get("password", "")).strip()}

    def validateCredential(self, data: Dict[str, Any]) -> None:
        if not str(data.get("username", "")).strip():
            raise ValueError("Basic Auth requires username.")
        # password may be empty per RFC but we allow it

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        username = str(cred.get("username", "")).strip()
        password = str(cred.get("password", "")).strip()
        if not username:
            raise ValueError("Basic Auth missing username")
        raw = f"{username}:{password}".encode()
        b64 = base64.b64encode(raw).decode()
        headers = dict(request.get("headers") or {})
        headers.setdefault("Authorization", f"Basic {b64}")
        request["headers"] = headers
        return request

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"username": data.get("username", ""), "password": "••••••••" if data.get("password") else ""}

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            return {"ok": True, "message": "Basic credentials present."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
