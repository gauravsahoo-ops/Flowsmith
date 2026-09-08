"""AuthProvider interface (spec: 12 architectural components).

Every authentication implementation follows this common contract.
Providers are discovered via AuthProviderRegistry — the HTTP Request node
never contains provider-specific logic.
"""
from __future__ import annotations

import abc
from typing import Any, Dict


class AuthProvider(abc.ABC):
    """Common interface for all authentication providers (generic + predefined).

    Methods:
    - resolveCredential: normalize raw credential data
    - validateCredential: raise ValueError if invalid
    - prepareRequest: mutate {headers, query, url} to add auth
    - refreshCredential: rotate tokens when applicable (OAuth2)
    - sanitize: remove secrets for logging
    - testConnection: probe credential validity (optional)
    """

    # Registry metadata — overridden by subclasses
    provider_id: str = ""
    display_name: str = ""
    auth_type: str = ""
    implemented: bool = True

    @abc.abstractmethod
    def resolveCredential(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize credential data (decrypted)."""
        raise NotImplementedError

    @abc.abstractmethod
    def validateCredential(self, data: Dict[str, Any]) -> None:
        """Validate credential; raise ValueError with clear message if invalid."""
        raise NotImplementedError

    @abc.abstractmethod
    def prepareRequest(self, request: Dict[str, Any], cred: Dict[str, Any]) -> Dict[str, Any]:
        """Mutate request dict {method, url, headers, query, body} to add auth.
        Returns modified request.
        """
        raise NotImplementedError

    def refreshCredential(self, data: Dict[str, Any]) -> Dict[str, Any] | None:
        """Rotate tokens when applicable. Return new data or None if not supported."""
        return None

    def sanitize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove secrets for logging; never expose raw secrets."""
        # Default: mask common secret keys
        out: Dict[str, Any] = {}
        for k, v in data.items():
            lk = k.lower()
            if any(s in lk for s in ("password", "secret", "token", "key", "api_key")):
                out[k] = "••••••••" if v else ""
            else:
                out[k] = v
        return out

    def testConnection(self, cred: Dict[str, Any]) -> Dict[str, Any]:
        """Probe credential validity. Default: validate only."""
        try:
            self.validateCredential(cred)
            return {"ok": True, "message": "Credential valid."}
        except Exception as e:
            return {"ok": False, "message": str(e)}
