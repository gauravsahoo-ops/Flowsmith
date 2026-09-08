"""Query Auth provider (API key in query)."""
from __future__ import annotations

from typing import Any, Dict

from .base import AuthProvider


class QueryAuthProvider(AuthProvider):
    provider_id = "query"
    display_name = "Query Auth"
    auth_type = "query"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = data.get("query_name") or data.get("name") or data.get("api_key_name") or "api_key"
        value = data.get("query_value") or data.get("value") or data.get("api_key") or data.get("token") or ""
        return {"query_name": str(name).strip(), "query_value": str(value).strip()}

    def validateCredential(self, data: Dict[str, Any]) -> None:
        cred = self.resolveCredential(data)
        if not cred["query_name"]:
            raise ValueError("Query Auth requires query parameter name.")
        if not cred["query_value"]:
            raise ValueError("Query Auth requires query parameter value.")

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(cred)
        query = dict(request.get("query") or {})
        if not cred["query_value"]:
            raise ValueError("Query value missing")
        query.setdefault(cred["query_name"], cred["query_value"])
        request["query"] = query
        return request

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(data)
        return {"query_name": cred["query_name"], "query_value": "••••••••" if cred["query_value"] else ""}

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            return {"ok": True, "message": "Query credentials present."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
