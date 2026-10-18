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
    {"id": "salesforce-jwt", "displayName": "Salesforce JWT", "category": "predefined", "authType": "oauth2", "provider": "salesforce_jwt", "implemented": True, "supportsOAuth": True, "supportsRefresh": False, "supportsTest": True},
    {"id": "github-oauth", "displayName": "GitHub OAuth", "category": "predefined", "authType": "oauth2", "provider": "github", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "google-oauth2", "displayName": "Google OAuth2 API", "category": "predefined", "authType": "oauth2", "provider": "google", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "slack-oauth2", "displayName": "Slack OAuth2", "category": "predefined", "authType": "oauth2", "provider": "slack", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "microsoft-oauth2", "displayName": "Microsoft OAuth2", "category": "predefined", "authType": "oauth2", "provider": "microsoft", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "hubspot-oauth2", "displayName": "HubSpot OAuth2", "category": "predefined", "authType": "oauth2", "provider": "hubspot", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
    {"id": "notion-api", "displayName": "Notion API", "category": "predefined", "authType": "header", "provider": "header", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "airtable-api", "displayName": "Airtable API", "category": "predefined", "authType": "header", "provider": "header", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "stripe-api", "displayName": "Stripe API", "category": "predefined", "authType": "bearer", "provider": "bearer", "implemented": True, "supportsOAuth": False, "supportsRefresh": False, "supportsTest": True},
    {"id": "shopify-oauth", "displayName": "Shopify OAuth", "category": "predefined", "authType": "oauth2", "provider": "shopify", "implemented": True, "supportsOAuth": True, "supportsRefresh": True, "supportsTest": True},
]


def _build_all_defs() -> List[Dict[str, Any]]:
    """Build complete catalog of predefined + connector credential types."""
    from app.credentials.registry import (
        CREDENTIAL_TYPES,
        TYPE_META,
        CREDENTIAL_PROVIDER,
        CREDENTIAL_IMPLEMENTED,
        PREDEFINED_CREDENTIALS,
    )
    from app.credentials.auth_metadata import CONNECTOR_AUTH_CATALOG

    defs = list(_PREDEFINED_DEFS)
    seen = {d["id"] for d in defs}

    oauth_types = frozenset({
        "oauth2", "oauth1", "salesforce", "hubspot", "dynamics_crm",
        "google_calendar", "google_sheets", "gmail", "google_drive", "google_docs",
        "zoho_crm", "xero", "box", "typeform", "sharepoint", "onedrive", "quickbooks",
    })
    refresh_types = frozenset({
        "oauth2", "salesforce", "hubspot", "dynamics_crm",
        "google_calendar", "google_sheets", "gmail", "google_drive", "google_docs",
        "quickbooks", "sharepoint", "onedrive",
    })

    # 1. Built-in Pydantic credential types
    for type_id in CREDENTIAL_TYPES:
        if type_id in seen:
            for d in defs:
                if d["id"] == type_id:
                    d["implemented"] = CREDENTIAL_IMPLEMENTED.get(type_id, True)
            continue

        meta = TYPE_META.get(type_id, {"name": type_id, "description": ""})
        auth_meta = CONNECTOR_AUTH_CATALOG.get(type_id, {})
        raw_auth = auth_meta.get("auth_method", "API Key")
        auth_str = raw_auth.value if hasattr(raw_auth, "value") else str(raw_auth)

        prov = "" if type_id == "http" else CREDENTIAL_PROVIDER.get(type_id, "header")
        is_impl = CREDENTIAL_IMPLEMENTED.get(type_id, True)

        defs.append({
            "id": type_id,
            "displayName": meta.get("name", type_id),
            "category": "connector",
            "authType": auth_str,
            "provider": prov,
            "implemented": is_impl,
            "supportsOAuth": type_id in oauth_types,
            "supportsRefresh": type_id in refresh_types,
            "supportsTest": is_impl,
        })
        seen.add(type_id)

    # 2. Connector-declared credentials
    try:
        from app.connectors import get_registry, ensure_builtin_connectors
        ensure_builtin_connectors()
        registry = get_registry()
        for info in registry.list_all():
            definition = registry.get_definition(info.connector_id)
            if not definition or not definition.credential_types:
                continue
            for ct_key, ct in definition.credential_types.items():
                if ct_key in seen:
                    continue
                seen.add(ct_key)
                name = getattr(ct, "display_name", "") or ct_key.replace("_", " ").title()
                desc = getattr(ct, "description", "") or f"Credentials for {name}."
                is_oauth = any("oauth" in s.lower() for s in [ct_key, name, desc])
                auth_str = "OAuth 2.0" if is_oauth else ("Bearer Token" if "token" in ct_key.lower() else "API Key")

                defs.append({
                    "id": ct_key,
                    "displayName": name,
                    "category": "connector",
                    "authType": auth_str,
                    "provider": "header",
                    "implemented": True,
                    "supportsOAuth": is_oauth,
                    "supportsRefresh": is_oauth,
                    "supportsTest": True,
                })
    except Exception:
        pass

    # 3. Predefined credentials
    for p in PREDEFINED_CREDENTIALS:
        pid = p.get("id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        auth = p.get("authType", "header")
        defs.append({
            "id": pid,
            "displayName": p.get("displayName", pid),
            "category": "predefined",
            "authType": auth,
            "provider": p.get("provider", "header"),
            "implemented": True,
            "supportsOAuth": auth in ("oauth2", "oauth1"),
            "supportsRefresh": auth == "oauth2",
            "supportsTest": True,
        })

    return defs


class CredentialTypeRegistry:
    def __init__(self, generic: List[Dict[str, Any]], predefined: List[Dict[str, Any]]) -> None:
        self._generic = generic
        self._predefined = predefined
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        all_predefined = _build_all_defs()
        self._by_id.clear()
        for entry in self._generic + all_predefined:
            self._by_id[entry["id"]] = dict(entry)

    def get(self, type_id: str) -> Dict[str, Any] | None:
        if not self._by_id:
            self.reload()
        return self._by_id.get(type_id)

    def list(self) -> List[Dict[str, Any]]:
        if not self._by_id:
            self.reload()
        return sorted(self._by_id.values(), key=lambda x: x["id"])

    def list_generic(self) -> List[Dict[str, Any]]:
        if not self._by_id:
            self.reload()
        return [v for v in self._by_id.values() if v.get("category") == "generic"]

    def list_predefined(self) -> List[Dict[str, Any]]:
        if not self._by_id:
            self.reload()
        return [v for v in self._by_id.values() if v.get("category") != "generic"]

    def is_implemented(self, type_id: str) -> bool:
        entry = self.get(type_id)
        if not entry:
            return False
        return bool(entry.get("implemented"))

    def provider_for(self, type_id: str) -> str | None:
        entry = self.get(type_id)
        if not entry:
            return None
        return entry.get("provider")


_credential_type_registry = CredentialTypeRegistry(_TYPE_DEFS, _PREDEFINED_DEFS)


def get_credential_type_registry() -> CredentialTypeRegistry:
    return _credential_type_registry

