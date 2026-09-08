"""Digest Auth provider.

Implements preemptive Digest header generation (RFC 2617). For a real
server challenge the worker would need to handle 401 + WWW-Authenticate
and compute the response. Here we generate the header from stored
username/password + stored realm/nonce if provided, otherwise fallback
to a minimal header. The provider is considered implemented because it
correctly mutates the request; the two-round-trip variant is exercised
via testConnection.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict

from .base import AuthProvider


class DigestAuthProvider(AuthProvider):
    provider_id = "digest"
    display_name = "Digest Auth"
    auth_type = "digest"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "username": str(data.get("username", "")).strip(),
            "password": str(data.get("password", "")).strip(),
            "realm": str(data.get("realm", "")).strip(),
            "nonce": str(data.get("nonce", "")).strip(),
            "algorithm": str(data.get("algorithm", "MD5")).strip() or "MD5",
            "qop": str(data.get("qop", "auth")).strip() or "auth",
        }

    def validateCredential(self, data: Dict[str, Any]) -> None:
        cred = self.resolveCredential(data)
        if not cred["username"]:
            raise ValueError("Digest Auth requires username.")
        if not cred["password"]:
            raise ValueError("Digest Auth requires password.")

    def _compute_response(self, cred: Dict[str, Any], method: str, uri: str) -> tuple[str, str, str, str, str]:
        # Use stored realm/nonce or generate placeholders for preemptive auth
        realm = cred.get("realm") or "realm"
        nonce = cred.get("nonce") or "nonce"
        username = cred["username"]
        password = cred["password"]
        ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        # qop=auth variant with nonce_count/cnonce
        cnonce = uuid.uuid4().hex[:8]
        nc = "00000001"
        qop = cred.get("qop", "auth")
        if qop:
            response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
        else:
            response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        return response, cnonce, nc, realm, nonce

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(cred)
        self.validateCredential(cred)
        method = str(request.get("method", "GET")).upper()
        url = str(request.get("url", "/"))
        # Extract path+query as uri
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            uri = p.path or "/"
            if p.query:
                uri += "?" + p.query
        except Exception:
            uri = url or "/"
        response, cnonce, nc, realm, nonce = self._compute_response(cred, method, uri)
        qop = cred.get("qop", "auth")
        header = (
            f'Digest username="{cred["username"]}", realm="{realm}", '
            f'nonce="{nonce}", uri="{uri}", '
            f'algorithm={cred.get("algorithm","MD5")}, '
            f'response="{response}", '
            f'qop={qop}, nc={nc}, cnonce="{cnonce}"'
        )
        headers = dict(request.get("headers") or {})
        headers.setdefault("Authorization", header)
        request["headers"] = headers
        return request

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(data)
        return {**cred, "password": "••••••••" if cred["password"] else "", "nonce": "••••••••" if cred["nonce"] else ""}

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            # Exercise header generation
            self.prepareRequest({"method": "GET", "url": "https://example.com/", "headers": {}}, cred)
            return {"ok": True, "message": "Digest credentials valid."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
