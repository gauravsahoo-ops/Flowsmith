"""CredentialTypeRegistry — catalog of credential types with provider mapping.

Separation:
- TypeRegistry: id → meta (displayName, category, authType, provider, implemented, supportsOAuth/Refresh/Test)
- SchemaRegistry: type → Pydantic schema
- ProviderRegistry: provider_id → AuthProvider (already exists)
"""
from __future__ import annotations

from typing import Any, Dict, List


# Predefined + generic type definitions — extended from existing CREDENTIAL_TYPES
# Each entry contains at minimum: id, displayName, category, authType, provider, implemented, supportsOAuth, supportsRefresh, supportsTest

_TYPE_DEFS: List[Dict[str, Any]] = [
    # Generic providers — all implemented
    {"id": "basic_auth", "displayName": "Basic Auth", "category": "generic", "authType": "basic", "provider": "basic", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "bearer_auth", "displayName": "Bearer Auth", "category": "generic", "authType": "bearer", "provider": "bearer", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "header_auth", "displayName": "Header Auth", "category": "generic", "authType": "header", "provider": "header", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "query_auth", "displayName": "Query Auth", "category": "generic", "authType": "query", "provider": "query", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "digest_auth", "displayName": "Digest Auth", "category": "generic", "authType": "digest", "provider": "digest", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "custom_auth", "displayName": "Custom Auth", "category": "generic", "authType": "custom", "provider": "custom", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "oauth2", "displayName": "OAuth2 API", "category": "generic", "authType": "oauth2", "provider": "oauth2", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "oauth1", "displayName": "OAuth1 API", "category": "generic", "authType": "oauth1", "provider": "oauth1", "implemented": True, "supportsOAuth": True, "supportsRefresh": False, "supportsTest": True},
]

# Predefined (business) — implemented only when provider exists
_PREDEFINED_DEFS: List[Dict[str, Any]] = [
    {"id": "salesforce-oauth2", "displayName": "Salesforce OAuth2 API", "category": "predefined", "authType": "oauth2", "provider": "salesforce", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "salesforce-jwt", "displayName": "Salesforce JWT", "category": "predefined", "authType": "oauth2", "provider": "salesforce_jwt", "implemented": False, "supportsOAuth": True, "supportsRefresh": False, "supportsTest": False},
    {"id": "github-oauth", "displayName": "GitHub OAuth", "category": "predefined", "authType": "oauth2", "provider": "github", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "google-oauth2", "displayName": "Google OAuth2 API", "category": "predefined", "authType": "oauth2", "provider": "google", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "slack-oauth2", "displayName": "Slack OAuth2", "category": "predefined", "authType": "oauth2", "provider": "slack", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "microsoft-oauth2", "displayName": "Microsoft OAuth2", "category": "predefined", "authType": "oauth2", "provider": "microsoft", "implemented": False, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": False},
    {"id": "hubspot-oauth2", "displayName": "HubSpot OAuth2", "category": "predefined", "authType": "oauth2", "provider": "hubspot", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "notion-api", "displayName": "Notion API", "category": "predefined", "authType": "header", "provider": "header", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "airtable-api", "displayName": "Airtable API", "category": "predefined", "authType": "header", "provider": "header", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "stripe-api", "displayName": "Stripe API", "category": "predefined", "authType": "bearer", "provider": "bearer", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "shopify-oauth", "displayName": "Shopify OAuth", "category": "predefined", "authType": "oauth2", "provider": "shopify", "implemented": False, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": False},
]


class CredentialTypeRegistry:
    def __init__(self, generic: List[Dict[str, Any]], predefined: List[Dict[str, Any]]) -> None:
        self._by_id: Dict[str, Dict[str, Any]] = {}
        for entry in generic + predefined:
            self._by_id[entry["id"]] = dict(entry)

    def get(self, type_id: str) -> Dict[str, Any] | None:
        return self._by_id.get(type_id)

    def list(self) -> List[Dict[str, Any]]:
        return sorted(self._by_id.values(), key=lambda x: x["id"])

    def list_generic(self) -> List[Dict[str, Any]]:
        return [v for v in self._by_id.values() if v["category"] == "generic"]

    def list_predefined(self) -> List[Dict[str, Any]]:
        return [v for v in self._by_id.values() if v["category"] == "predefined"]

    def is_implemented(self, type_id: str) -> bool:
        entry = self._by_id.get(type_id)
        if not entry:
            return False
        return bool(entry.get("implemented"))

    def provider_for(self, type_id: str) -> str | None:
        entry = self._by_id.get(type_id)
        if not entry:
            return None
        return entry.get("provider")


_credential_type_registry = CredentialTypeRegistry(_TYPE_DEFS, _PREDEFINED_DEFS)


def get_credential_type_registry() -> CredentialTypeRegistry:
    return _credential_type_registry
