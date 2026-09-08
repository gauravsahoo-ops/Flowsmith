"""OAuth1 provider (HMAC-SHA1 signing)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from typing import Any, Dict
from urllib.parse import quote


from .base import AuthProvider


class OAuth1Provider(AuthProvider):
    provider_id = "oauth1"
    display_name = "OAuth1 API"
    auth_type = "oauth1"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "consumer_key": str(data.get("consumer_key", "") or data.get("consumerKey", "") or data.get("client_id", "")).strip(),
            "consumer_secret": str(data.get("consumer_secret", "") or data.get("consumerSecret", "") or data.get("client_secret", "")).strip(),
            "token": str(data.get("token", "") or data.get("access_token", "")).strip(),
            "token_secret": str(data.get("token_secret", "") or data.get("tokenSecret", "")).strip(),
            "signature_method": str(data.get("signature_method", "HMAC-SHA1")).strip() or "HMAC-SHA1",
        }

    def validateCredential(self, data: Dict[str, Any]) -> None:
        cred = self.resolveCredential(data)
        if not cred["consumer_key"]:
            raise ValueError("OAuth1 requires consumer_key.")
        if not cred["consumer_secret"]:
            raise ValueError("OAuth1 requires consumer_secret.")
        if not cred["token"]:
            raise ValueError("OAuth1 requires token.")
        if not cred["token_secret"]:
            raise ValueError("OAuth1 requires token_secret.")

    def _oauth_params(self, cred: Dict[str, Any]) -> Dict[str, str]:
        return {
            "oauth_consumer_key": cred["consumer_key"],
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": cred["signature_method"],
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": cred["token"],
            "oauth_version": "1.0",
        }

    def _sign(self, method: str, url: str, params: Dict[str, Any], cred: Dict[str, Any]) -> str:
        # Collect all params (query + oauth)
        all_params = dict(params)
        oauth = self._oauth_params(cred)
        all_params.update(oauth)
        # Sort and encode
        sorted_kv = sorted((quote(str(k), safe=""), quote(str(v), safe="")) for k, v in all_params.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_kv)
        base_url = url.split("?", 1)[0]
        base_string = "&".join([method.upper(), quote(base_url, safe=""), quote(param_str, safe="")])
        signing_key = f"{quote(cred['consumer_secret'], safe='')}&{quote(cred['token_secret'], safe='')}"
        hashed = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1)
        signature = base64.b64encode(hashed.digest()).decode()
        oauth["oauth_signature"] = signature
        # Build header
        header_params = ", ".join(f'{quote(k, safe="")}="{quote(v, safe="")}"' for k, v in sorted(oauth.items()))
        return f"OAuth {header_params}"

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(cred)
        self.validateCredential(cred)
        method = str(request.get("method", "GET"))
        url = str(request.get("url", ""))
        query = dict(request.get("query") or {})
        headers = dict(request.get("headers") or {})
        auth_header = self._sign(method, url, query, cred)
        headers.setdefault("Authorization", auth_header)
        request["headers"] = headers
        return request

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(data)
        return {
            "consumer_key": cred["consumer_key"][:4] + "••••" if cred["consumer_key"] else "",
            "consumer_secret": "••••••••" if cred["consumer_secret"] else "",
            "token": cred["token"][:4] + "••••" if cred["token"] else "",
            "token_secret": "••••••••" if cred["token_secret"] else "",
            "signature_method": cred["signature_method"],
        }

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            # Exercise signing
            self.prepareRequest({"method": "GET", "url": "https://example.com/resource", "query": {}, "headers": {}}, cred)
            return {"ok": True, "message": "OAuth1 credentials valid."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
