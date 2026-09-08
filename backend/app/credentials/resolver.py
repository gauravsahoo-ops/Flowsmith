"""CredentialResolver — resolves credentialId → decrypted data + provider.

Flow:
workflow node (credentialId + credentialType)
  → CredentialResolver
  → CredentialStore (decrypt)
  → provider lookup
  → validated auth data
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from sqlalchemy.orm import Session

from .credential_store import get_credential_store
from .provider_registry import get_provider_registry
from .type_registry import get_credential_type_registry
from app.credentials.service import CredentialError


class CredentialResolver:
    def resolve(self, db: Session, user_id: int, cred_type: str, cred_id: str) -> Tuple[Dict[str, Any], Any]:
        """Return (decrypted_data, provider_instance). Raises CredentialError or ValueError."""
        if not cred_id:
            raise CredentialError("Missing credentialId.", code="CREDENTIALS_REQUIRED")
        # Verify type is known and implemented
        type_reg = get_credential_type_registry()
        type_entry = type_reg.get(cred_type)
        # Fallback to legacy types from existing registry if not in new type registry
        if not type_entry:
            from .registry import is_known_type
            if not is_known_type(cred_type):
                raise ValueError(f"Unknown credential type '{cred_type}'.")
            # Legacy types are considered implemented if they exist in CREDENTIAL_TYPES
            provider_id = cred_type  # legacy: type == provider hint
        else:
            if not type_entry.get("implemented"):
                raise ValueError(f"Authentication provider '{type_entry.get('provider')}' for '{cred_type}' not implemented yet.")
            provider_id = type_entry.get("provider") or cred_type

        store = get_credential_store()
        rec = store.get_encrypted(db, user_id, cred_id)
        if rec.type != cred_type:
            raise CredentialError(f"Credential '{rec.name}' is type '{rec.type}', expected '{cred_type}'.", code="CREDENTIALS_REQUIRED")
        data = store.decrypt(rec)

        # Provider lookup: try provider_id, then auth_type
        prov_reg = get_provider_registry()
        provider = prov_reg.get(provider_id)
        if provider is None:
            # Try auth_type mapping
            provider = prov_reg.get_by_auth_type(provider_id)
        if provider is None and type_entry:
            # Try authType field
            provider = prov_reg.get_by_auth_type(type_entry.get("authType", ""))
        # If still not found, for legacy types like 'salesforce' etc, they are not HTTP auth providers — allow passthrough
        # But for generic auth, we require provider
        generic_types = {"basic_auth", "bearer_auth", "header_auth", "query_auth", "digest_auth", "custom_auth", "oauth2", "oauth1"}
        if cred_type in generic_types and provider is None:
            raise ValueError(f"Authentication provider not implemented yet for '{cred_type}'.")

        # Validate
        if provider is not None:
            provider.validateCredential(data)

        return data, provider

    def resolve_map(self, db: Session, user_id: int, refs: Dict[str, str]) -> Dict[str, Any]:
        """Resolve map {cred_type: cred_id} → {cred_type: decrypted_data}."""
        out: Dict[str, Any] = {}
        for ctype, cid in refs.items():
            data, _ = self.resolve(db, user_id, ctype, cid)
            if isinstance(data, dict):
                data["_credential_id"] = cid
            out[ctype] = data
        return out


_resolver = CredentialResolver()


def get_credential_resolver() -> CredentialResolver:
    return _resolver
