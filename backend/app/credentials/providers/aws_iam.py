"""AWS IAM — SigV4 request signing."""
from typing import Any, Dict
import hashlib
import hmac
import time
from urllib.parse import urlparse
from .base import AuthProvider

class AwsIamAuthProvider(AuthProvider):
    provider_id = "aws_iam"
    display_name = "AWS IAM"
    auth_type = "aws_iam"
    implemented = True
    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "access_key": str(data.get("access_key", "") or data.get("aws_access_key", "")).strip(),
            "secret_key": str(data.get("secret_key", "") or data.get("aws_secret_key", "")).strip(),
            "region": str(data.get("region", "") or data.get("aws_region", "") or "us-east-1").strip() or "us-east-1",
            "service": str(data.get("service", "") or "execute-api").strip() or "execute-api",
            "session_token": str(data.get("session_token", "") or data.get("aws_session_token", "")).strip(),
        }
    def validateCredential(self, data: Dict[str, Any]) -> None:
        c = self.resolveCredential(data)
        if not c["access_key"]:
            raise ValueError("AWS IAM requires access_key.")
        if not c["secret_key"]:
            raise ValueError("AWS IAM requires secret_key.")
    def _sign(self, cred: Dict[str, Any], request: Dict[str, Any]) -> Dict[str, str]:
        c = self.resolveCredential(cred)
        method = str(request.get("method", "GET")).upper()
        url = str(request.get("url", ""))
        headers = dict(request.get("headers") or {})
        # Minimal SigV4 headers
        now = time.gmtime()
        amz_date = time.strftime("%Y%m%dT%H%M%SZ", now)
        date_stamp = time.strftime("%Y%m%d", now)
        parsed = urlparse(url)
        host = parsed.netloc
        canonical_uri = parsed.path or "/"
        canonical_querystring = parsed.query or ""
        # Headers to sign
        headers["host"] = host
        headers["x-amz-date"] = amz_date
        if c["session_token"]:
            headers["x-amz-security-token"] = c["session_token"]
        # Payload hash
        payload_hash = hashlib.sha256((request.get("body") or "").encode() if isinstance(request.get("body"), str) else b"").hexdigest()
        headers["x-amz-content-sha256"] = payload_hash
        signed_headers_list = sorted(k.lower() for k in headers.keys())
        signed_headers = ";".join(signed_headers_list)
        canonical_headers = "".join(f"{k.lower()}:{headers[k].strip()}\n" for k in sorted(headers.keys(), key=lambda x: x.lower()))
        canonical_request = f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{c['region']}/{c['service']}/aws4_request"
        string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        # Signing key
        k_secret = ("AWS4" + c["secret_key"]).encode()
        k_date = hmac.new(k_secret, date_stamp.encode(), hashlib.sha256).digest()
        k_region = hmac.new(k_date, c["region"].encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_region, c["service"].encode(), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
        auth_header = f"{algorithm} Credential={c['access_key']}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
        return {"Authorization": auth_header, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash, **({"x-amz-security-token": c["session_token"]} if c["session_token"] else {})}
    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        c = self.resolveCredential(cred)
        self.validateCredential(c)
        signed = self._sign(c, request)
        h = dict(request.get("headers") or {})
        h.update(signed)
        request["headers"] = h
        return request
    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        c = self.resolveCredential(data)
        return {k: ("••••••••" if "key" in k.lower() or k == "secret_key" else v) for k, v in c.items()}
    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            # Test signing
            self._sign(cred, {"method":"GET","url":"https://example.amazonaws.com/","headers":{}})
            return {"ok": True, "message": "AWS IAM credentials present and signable."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
