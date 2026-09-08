"""Custom Auth provider — arbitrary headers/query/body injection."""
from __future__ import annotations

from typing import Any, Dict

from .base import AuthProvider


class CustomAuthProvider(AuthProvider):
    provider_id = "custom"
    display_name = "Custom Auth"
    auth_type = "custom"
    implemented = True

    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        headers = data.get("headers") or data.get("custom_headers") or {}
        query = data.get("query") or data.get("custom_query") or {}
        body = data.get("body") or {}
        prefix = data.get("prefix") or ""
        # Normalize
        if not isinstance(headers, dict):
            headers = {}
        if not isinstance(query, dict):
            query = {}
        return {
            "headers": {str(k): str(v) for k, v in headers.items() if k},
            "query": {str(k): str(v) for k, v in query.items() if k},
            "body": body,
            "prefix": str(prefix),
        }

    def validateCredential(self, data: Dict[str, Any]) -> None:
        cred = self.resolveCredential(data)
        if not cred["headers"] and not cred["query"] and not cred["body"]:
            raise ValueError("Custom Auth requires at least one of headers/query/body.")

    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(cred)
        self.validateCredential(cred)
        headers = dict(request.get("headers") or {})
        query = dict(request.get("query") or {})
        # Merge custom headers (do not overwrite existing)
        for k, v in cred["headers"].items():
            headers.setdefault(k, v)
        for k, v in cred["query"].items():
            query.setdefault(k, v)
        request["headers"] = headers
        request["query"] = query
        # Body injection for custom body (merge if both dicts)
        if cred["body"]:
            body = request.get("body")
            if isinstance(body, dict) and isinstance(cred["body"], dict):
                merged = dict(body)
                merged.update(cred["body"])
                request["body"] = merged
            elif not body:
                request["body"] = cred["body"]
        return request

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cred = self.resolveCredential(data)
        # Mask values that look like secrets
        def mask(d: Dict[str, Any]) -> Dict[str, Any]:
            out = {}
            for k, v in d.items():
                lk = k.lower()
                if any(s in lk for s in ("token", "key", "secret", "password")):
                    out[k] = "••••••••"
                else:
                    out[k] = v
            return out
        return {"headers": mask(cred["headers"]), "query": mask(cred["query"]), "body": cred["body"]}

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.validateCredential(cred)
            return {"ok": True, "message": "Custom auth present."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
