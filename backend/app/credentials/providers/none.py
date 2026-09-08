"""None auth — no authentication."""
from typing import Any, Dict
from .base import AuthProvider
class NoneAuthProvider(AuthProvider):
    provider_id = "none"
    display_name = "No Auth"
    auth_type = "none"
    implemented = True
    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {}
    def validateCredential(self, data: Dict[str, Any]) -> None:
        return
    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        return request
    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {}
    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "message": "No auth required."}
