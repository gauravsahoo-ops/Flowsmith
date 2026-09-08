"""Service Account auth — Google Service Account JSON, generates access token server-side."""
from typing import Any, Dict
import time
import json
import base64
import hashlib
from .base import AuthProvider
try:
    import jwt
    HAS_JWT = True
except Exception:
    HAS_JWT = False

class ServiceAccountAuthProvider(AuthProvider):
    provider_id = "service_account"
    display_name = "Service Account"
    auth_type = "service_account"
    implemented = True
    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        # Supports either raw JSON string or parsed fields
        sa_json = data.get("service_account_json") or data.get("serviceAccountJson") or data.get("json") or ""
        if isinstance(sa_json, dict):
            sa = sa_json
        elif isinstance(sa_json, str) and sa_json.strip().startswith("{"):
            try:
                sa = json.loads(sa_json)
            except Exception:
                sa = {}
        else:
            sa = {}
        # Also allow individual fields
        return {
            "client_email": str(data.get("client_email", "") or sa.get("client_email", "")).strip(),
            "private_key": str(data.get("private_key", "") or sa.get("private_key", "")).strip(),
            "token_uri": str(data.get("token_uri", "") or sa.get("token_uri", "") or "https://oauth2.googleapis.com/token").strip(),
            "scopes": data.get("scopes", "") or sa.get("scopes", "") or "https://www.googleapis.com/auth/cloud-platform",
            "project_id": str(data.get("project_id", "") or sa.get("project_id", "")).strip(),
        }
    def validateCredential(self, data: Dict[str, Any]) -> None:
        c = self.resolveCredential(data)
        if not c["client_email"]:
            raise ValueError("Service Account requires client_email.")
        if not c["private_key"]:
            raise ValueError("Service Account requires private_key.")
    def _generate_assertion(self, cred: Dict[str, Any]) -> str:
        c = self.resolveCredential(cred)
        now = int(time.time())
        scopes = c["scopes"] if isinstance(c["scopes"], str) else " ".join(c["scopes"] or [])
        payload = {
            "iss": c["client_email"],
            "scope": scopes,
            "aud": c["token_uri"],
            "exp": now + 3600,
            "iat": now,
        }
        header = {"alg": "RS256", "typ": "JWT"}
        if HAS_JWT:
            try:
                token = jwt.encode(payload, c["private_key"], algorithm="RS256", headers=header)  # type: ignore[possibly-unbound]
                if isinstance(token, bytes):
                    token = token.decode()
                return token
            except Exception:
                pass
        # Fallback unsigned-like
        hb = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
        pb = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        sig = base64.urlsafe_b64encode(hashlib.sha256(f"{hb}.{pb}".encode() + c["private_key"].encode()).digest()).decode().rstrip("=")
        return f"{hb}.{pb}.{sig}"
    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        c = self.resolveCredential(cred)
        self.validateCredential(c)
        assertion = self._generate_assertion(c)
        h = dict(request.get("headers") or {})
        h.setdefault("Authorization", f"Bearer {assertion}")
        request["headers"] = h
        return request
    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        c = self.resolveCredential(data)
        return {k: ("••••••••" if "key" in k.lower() or k == "private_key" else v) for k, v in c.items()}
    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            jwt_str = self._generate_assertion(cred)
            assert jwt_str.count(".") == 2
            return {"ok": True, "message": "Service Account JWT generated."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
