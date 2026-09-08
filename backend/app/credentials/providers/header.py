"""Header Auth provider (API key in header)."""
from __future__ import annotations

from typing import Any, Dict

from .base import AuthProvider


class HeaderAuthProvider(AuthProvider):
    provider_id = "header"
    display_name = "Header Auth"
    auth_type = "header"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = data.get("header_name") or data.get("name") or data.get("api_key_name") or "X-API-Key"
        value = data.get("header_value") or data.get("value") or data.get("api_key") or data.get("token") or ""
        return {"header_name": str(name).strip(), "header_value": str(value).strip()}

    def validateCredential(self, data: Dict[str, Any]) -> None:
        cred = self.resolveCredential(data)
        if not cred["header_name"]:
            raise ValueError("Header Auth requires header name.")
        if not cred["header_value"]:
            raise ValueError("Header Auth requires header value.")

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(cred)
        headers = dict(request.get("headers") or {})
        name = cred["header_name"] or "X-API-Key"
        if not cred["header_value"]:
            raise ValueError("Header value missing")
        headers.setdefault(name, cred["header_value"])
        request["headers"] = headers
        return request

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(data)
        return {"header_name": cred["header_name"], "header_value": "••••••••" if cred["header_value"] else ""}

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            return {"ok": True, "message": "Header credentials present."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
