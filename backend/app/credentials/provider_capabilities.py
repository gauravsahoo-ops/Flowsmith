"""Provider Capabilities Abstraction.

Declares explicit authentication capabilities, refresh grants, and recovery
behaviors for each integration provider (OAuth, Client Credentials, API Keys, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class ProviderCapability:
    """Explicit capabilities supported by an integration auth provider."""

    provider: str
    display_name: str
    auth_type: str  # oauth2 | client_credentials | api_key | basic | bearer | custom

    supports_refresh: bool = False
    supports_rotation: bool = False
    supports_client_credentials: bool = False
    requires_interactive_reauth: bool = False
    supports_health_check: bool = True
    supports_revocation: bool = False
    default_cooldown_seconds: int = 60
    max_recovery_retries: int = 4

    def can_auto_recover(self, cred_data: Dict[str, Any]) -> bool:
        """Evaluate if specific credential data has required material for auto-recovery."""
        if self.supports_client_credentials:
            has_client = bool(cred_data.get("client_id") and cred_data.get("client_secret"))
            if has_client:
                return True

        if self.supports_refresh:
            if cred_data.get("refresh_token_expired") or cred_data.get("refresh_token_revoked"):
                return False
            return bool(cred_data.get("refresh_token"))

        return False


# Registry of known provider capabilities
_CAPABILITIES: dict[str, ProviderCapability] = {
    # 1. Salesforce (OAuth2 with refresh token & rotation, instance url updates)
    "salesforce": ProviderCapability(
        provider="salesforce",
        display_name="Salesforce",
        auth_type="oauth2",
        supports_refresh=True,
        supports_rotation=True,
        supports_client_credentials=False,
        requires_interactive_reauth=False,
        supports_health_check=True,
        supports_revocation=True,
        default_cooldown_seconds=30,
        max_recovery_retries=5,
    ),
    # 2. Microsoft Dynamics 365 (Dual-mode: Interactive OAuth with PKCE vs S2S Service Principal)
    "dynamics_crm": ProviderCapability(
        provider="dynamics_crm",
        display_name="Microsoft Dynamics 365 / Dataverse",
        auth_type="oauth2",
        supports_refresh=True,
        supports_rotation=True,
        supports_client_credentials=True,
        requires_interactive_reauth=False,
        supports_health_check=True,
        supports_revocation=False,
        default_cooldown_seconds=30,
        max_recovery_retries=5,
    ),
    # 3. HubSpot (OAuth2 refresh tokens & Private App tokens)
    "hubspot": ProviderCapability(
        provider="hubspot",
        display_name="HubSpot",
        auth_type="oauth2",
        supports_refresh=True,
        supports_rotation=True,
        supports_client_credentials=False,
        requires_interactive_reauth=False,
        supports_health_check=True,
        supports_revocation=True,
        default_cooldown_seconds=60,
        max_recovery_retries=4,
    ),
    # 4. Google Workspace / APIs
    "google": ProviderCapability(
        provider="google",
        display_name="Google",
        auth_type="oauth2",
        supports_refresh=True,
        supports_rotation=False,
        supports_client_credentials=False,
        requires_interactive_reauth=False,
        supports_health_check=True,
        supports_revocation=True,
        default_cooldown_seconds=60,
        max_recovery_retries=4,
    ),
    # 5. Generic OAuth2
    "oauth2": ProviderCapability(
        provider="oauth2",
        display_name="OAuth 2.0",
        auth_type="oauth2",
        supports_refresh=True,
        supports_rotation=True,
        supports_client_credentials=True,
        requires_interactive_reauth=False,
        supports_health_check=True,
        supports_revocation=False,
        default_cooldown_seconds=60,
        max_recovery_retries=4,
    ),
    # 6. Static API Keys / Bearer Tokens / Headers
    "api_key": ProviderCapability(
        provider="api_key",
        display_name="API Key",
        auth_type="api_key",
        supports_refresh=False,
        supports_rotation=False,
        supports_client_credentials=False,
        requires_interactive_reauth=True,
        supports_health_check=True,
        supports_revocation=False,
    ),
    "bearer_auth": ProviderCapability(
        provider="bearer_auth",
        display_name="Bearer Token",
        auth_type="bearer",
        supports_refresh=False,
        supports_rotation=False,
        supports_client_credentials=False,
        requires_interactive_reauth=True,
        supports_health_check=True,
        supports_revocation=False,
    ),
    "basic_auth": ProviderCapability(
        provider="basic_auth",
        display_name="Basic Auth",
        auth_type="basic",
        supports_refresh=False,
        supports_rotation=False,
        supports_client_credentials=False,
        requires_interactive_reauth=True,
        supports_health_check=True,
        supports_revocation=False,
    ),
}


def get_provider_capability(provider_or_type: str) -> ProviderCapability:
    """Retrieve capability profile by provider name or credential type."""
    key = (provider_or_type or "").strip().lower()

    # Direct match
    if key in _CAPABILITIES:
        return _CAPABILITIES[key]

    # Map aliases
    if any(k in key for k in ("salesforce", "sf")):
        return _CAPABILITIES["salesforce"]
    if any(k in key for k in ("dynamics", "dataverse", "crm")):
        return _CAPABILITIES["dynamics_crm"]
    if "hubspot" in key:
        return _CAPABILITIES["hubspot"]
    if any(k in key for k in ("google", "gmail", "calendar", "sheets", "drive")):
        return _CAPABILITIES["google"]
    if "oauth" in key:
        return _CAPABILITIES["oauth2"]

    # Fallback to static credential profile
    return ProviderCapability(
        provider=key or "custom",
        display_name=(key or "Custom").replace("_", " ").title(),
        auth_type="static",
        supports_refresh=False,
        supports_rotation=False,
        supports_client_credentials=False,
        requires_interactive_reauth=True,
        supports_health_check=True,
        supports_revocation=False,
    )
