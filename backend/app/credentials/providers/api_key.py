"""API Key auth — header or query."""
from typing import Any, Dict
from .base import AuthProvider
class ApiKeyAuthProvider(AuthProvider):
    provider_id = "api_key"
    display_name = "API Key"
    auth_type = "api_key"
    implemented = True
    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        name = data.get("api_key_name") or data.get("name") or data.get("header_name") or "X-API-Key"
        value = data.get("api_key") or data.get("value") or data.get("token") or ""
        where = data.get("api_key_in") or data.get("in") or "header"
        return {"name": str(name).strip(), "value": str(value).strip(), "in": str(where).strip().lower()}
    def validateCredential(self, data: Dict[str, Any]) -> None:
        c = self.resolveCredential(data)
        if not c["name"]:
            raise ValueError("API Key requires name.")
        if not c["value"]:
            raise ValueError("API Key requires value.")
        if c["in"] not in ("header","query"):
            raise ValueError("API Key 'in' must be header or query.")
    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        c = self.resolveCredential(cred)
        self.validateCredential(c)
        if c["in"] == "query":
            q = dict(request.get("query") or {})
            q.setdefault(c["name"], c["value"])
            request["query"] = q
        else:
            h = dict(request.get("headers") or {})
            h.setdefault(c["name"], c["value"])
            request["headers"] = h
        return request
    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        c = self.resolveCredential(data)
        return {"name": c["name"], "value": "••••••••" if c["value"] else "", "in": c["in"]}
    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            return {"ok": True, "message": "API Key present."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
