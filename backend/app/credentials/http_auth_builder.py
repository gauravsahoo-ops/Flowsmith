"""HttpAuthBuilder — applies provider auth to outgoing request."""
from __future__ import annotations

from typing import Any, Dict

from .provider_registry import get_provider_registry


class HttpAuthBuilder:
    """Builds authenticated request dict via AuthProvider.

    Request shape: {method, url, headers, query, body}
    Returns modified request.
    """

    def build(self, request: Dict[str, Any], provider_id: str, cred: Dict[str, Any]) -> Dict[str, Any]:
        reg = get_provider_registry()
        provider = reg.get(provider_id) or reg.get_by_auth_type(provider_id)
        if provider is None:
            raise ValueError(f"Authentication provider '{provider_id}' not implemented yet.")
        if not provider.implemented:
            raise ValueError(f"Authentication provider '{provider_id}' not implemented yet.")
        # Validate before mutate
        provider.validateCredential(cred)
        # Resolve — prepareRequest expects resolved shape (e.g. {"token": ...})
        resolved = provider.resolveCredential(cred)
        # Prepare — mutate headers/query
        return provider.prepareRequest(dict(request), resolved)

    def sanitize_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Redact secrets in request for logging."""
        headers = dict(request.get("headers") or {})
        redacted: Dict[str, str] = {}
        for k, v in headers.items():
            lk = k.lower()
            if any(s in lk for s in ("authorization", "cookie", "x-api-key", "x-auth-token", "token", "secret", "key")):
                redacted[k] = "••••••••"
            else:
                redacted[k] = v
        out = dict(request)
        out["headers"] = redacted
        return out


_builder = HttpAuthBuilder()


def get_http_auth_builder() -> HttpAuthBuilder:
    return _builder
