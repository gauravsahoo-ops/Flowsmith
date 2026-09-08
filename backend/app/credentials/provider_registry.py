"""AuthProviderRegistry — discovers generic + predefined providers.

Adding a provider requires:
1. credential definition (type)
2. credential schema (Pydantic)
3. authentication provider class (AuthProvider)
4. registration (register)
5. tests

The HTTP Request node discovers providers only through this registry.
"""
from __future__ import annotations

from typing import Dict, Type

from .providers.base import AuthProvider


class AuthProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, Type[AuthProvider]] = {}
        self._instances: Dict[str, AuthProvider] = {}

    def register(self, provider_cls: Type[AuthProvider]) -> Type[AuthProvider]:
        pid = getattr(provider_cls, "provider_id", "")
        if not pid:
            raise ValueError(f"Provider {provider_cls.__name__} missing provider_id")
        self._providers[pid] = provider_cls
        # Clear cached instance if re-registering
        self._instances.pop(pid, None)
        return provider_cls

    def get(self, provider_id: str) -> AuthProvider | None:
        cls = self._providers.get(provider_id)
        if cls is None:
            return None
        if provider_id not in self._instances:
            self._instances[provider_id] = cls()
        return self._instances[provider_id]

    def get_by_auth_type(self, auth_type: str) -> AuthProvider | None:
        # auth_type maps 1:1 to provider_id for generic providers
        return self.get(auth_type)

    def list(self) -> list[Dict[str, object]]:
        out = []
        for pid, cls in self._providers.items():
            inst = self.get(pid)
            out.append({
                "id": pid,
                "displayName": getattr(cls, "display_name", pid),
                "authType": getattr(cls, "auth_type", pid),
                "implemented": bool(getattr(cls, "implemented", True)),
            })
        return sorted(out, key=lambda x: x["id"])

    def is_implemented(self, provider_id: str) -> bool:
        p = self.get(provider_id)
        if p is None:
            return False
        return bool(getattr(p, "implemented", True))

    def __contains__(self, provider_id: str) -> bool:
        return provider_id in self._providers


# Global singleton
_provider_registry = AuthProviderRegistry()


def get_provider_registry() -> AuthProviderRegistry:
    return _provider_registry


def _load_builtin_providers() -> None:
    from .providers.basic import BasicAuthProvider
    from .providers.bearer import BearerAuthProvider
    from .providers.header import HeaderAuthProvider
    from .providers.query import QueryAuthProvider
    from .providers.digest import DigestAuthProvider
    from .providers.custom import CustomAuthProvider
    from .providers.oauth1 import OAuth1Provider
    from .providers.oauth2 import OAuth2Provider
    from .providers.none import NoneAuthProvider
    from .providers.api_key import ApiKeyAuthProvider
    from .providers.pat import PatAuthProvider
    from .providers.jwt import JwtAuthProvider
    from .providers.service_account import ServiceAccountAuthProvider
    from .providers.aws_iam import AwsIamAuthProvider
    from .providers.aws_assume_role import AwsAssumeRoleAuthProvider
    from .providers.salesforce import SalesforceAuthProvider

    for cls in [
        BasicAuthProvider,
        BearerAuthProvider,
        HeaderAuthProvider,
        QueryAuthProvider,
        DigestAuthProvider,
        CustomAuthProvider,
        OAuth1Provider,
        OAuth2Provider,
        NoneAuthProvider,
        ApiKeyAuthProvider,
        PatAuthProvider,
        JwtAuthProvider,
        ServiceAccountAuthProvider,
        AwsIamAuthProvider,
        AwsAssumeRoleAuthProvider,
        SalesforceAuthProvider,
    ]:
        _provider_registry.register(cls)


_load_builtin_providers()
