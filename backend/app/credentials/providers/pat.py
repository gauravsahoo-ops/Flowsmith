"""PAT (Personal Access Token) — typically Bearer or Header."""
from typing import Any, Dict
from .base import AuthProvider
class PatAuthProvider(AuthProvider):
    provider_id = "pat"
    display_name = "Personal Access Token"
    auth_type = "pat"
    implemented = True
    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        token = data.get("personal_access_token") or data.get("pat") or data.get("token") or data.get("api_key") or ""
        return {"token": str(token).strip()}
    def validateCredential(self, data: Dict[str, Any]) -> None:
        c = self.resolveCredential(data)
        if not c["token"]:
            raise ValueError("PAT requires token.")
    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        c = self.resolveCredential(cred)
        self.validateCredential(c)
        h = dict(request.get("headers") or {})
        # PAT is typically sent as Authorization: Bearer or Private-Token
        # Use Bearer by default, but allow provider-specific header via extra field
        header_name = cred.get("header_name") or "Authorization"
        if header_name.lower() == "authorization":
            h.setdefault(header_name, f"Bearer {c['token']}")
        else:
            h.setdefault(header_name, c["token"])
        request["headers"] = h
        return request
    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"token": "••••••••" if self.resolveCredential(data).get("token") else ""}
    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            return {"ok": True, "message": "PAT present."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
