"""Credential persistence + resolution (spec 12, 29).

API responses only ever contain metadata `{id, name, type}` (spec
12.1: frontend never sees decrypted data). Resolution decrypts
immediately before node execution and raises typed errors for missing
or undecryptable credentials.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.credentials.registry import validate_data
from app.models.credential import Credential
from app.security.crypto import CredentialDecryptionError, decrypt_text, encrypt_text
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger("credentials")


class CredentialError(Exception):
    """Typed credential failure (missing, wrong owner, undecryptable)."""

    def __init__(self, message: str, code: str = "CREDENTIALS_REQUIRED") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def to_meta(rec: Credential) -> dict[str, str]:
    return {"id": rec.id, "name": rec.name, "type": rec.type}


def list_for_user(db: Session, user_id: int) -> list[dict[str, str]]:
    recs = db.scalars(
        select(Credential).where(Credential.user_id == user_id).order_by(Credential.created_at.desc())
    ).all()
    return [to_meta(r) for r in recs]


def create_for_user(db: Session, user_id: int, name: str, cred_type: str, data: dict[str, Any]) -> dict[str, str]:
    """Validate -> encrypt -> store. Returns metadata only."""
    normalized = validate_data(cred_type, data)
    blob = encrypt_text(json.dumps(normalized, ensure_ascii=False))
    rec = Credential(id=f"cred_{uuid.uuid4().hex[:12]}", user_id=user_id, name=name, type=cred_type, data=blob)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return to_meta(rec)


def delete_for_user(db: Session, user_id: int, credential_id: str) -> None:
    rec = db.get(Credential, credential_id)
    if rec is None or rec.user_id != user_id:
        raise CredentialError("Credential not found.", code="CREDENTIAL_NOT_FOUND")
    db.delete(rec)
    db.commit()


async def logout_for_user(db: Session, user_id: int, credential_id: str) -> dict[str, Any]:
    """Revoke tokens on the upstream provider (if supported) and delete the credential completely."""
    rec = db.get(Credential, credential_id)
    if rec is None or rec.user_id != user_id:
        raise CredentialError("Credential not found.", code="CREDENTIAL_NOT_FOUND")

    cred_type = rec.type
    cred_name = rec.name
    revoked = False
    provider_key = None

    try:
        decrypted = json.loads(decrypt_text(rec.data))
    except Exception:
        decrypted = {}

    if isinstance(decrypted, dict) and decrypted.get("oauth"):
        from app.config import get_settings
        from app.oauth_providers import PROVIDERS

        spec = next((s for s in PROVIDERS.values() if s.credential_type == cred_type), None)
        if spec and spec.revoke_token:
            provider_key = spec.key
            try:
                async with get_safe_http_client() as client:
                    revoked = await spec.revoke_token(client, get_settings(), decrypted)
            except Exception as exc:
                logger.warning("Revocation failed during logout for %s: %s", credential_id, exc)

    db.delete(rec)
    db.commit()

    return {
        "id": credential_id,
        "name": cred_name,
        "type": cred_type,
        "provider": provider_key,
        "revoked": bool(revoked),
        "message": f"Credential '{cred_name}' logged out and revoked completely.",
    }


def reencrypt_all(db: Session) -> int:
    """Re-encrypt every stored credential with the CURRENT encryption
    key (run after prepending a new key to CREDENTIALS_ENCRYPTION_KEY
    to finish the rotation). Returns the number of credentials updated."""
    recs = db.scalars(select(Credential)).all()
    count = 0
    for rec in recs:
        try:
            plaintext = decrypt_text(rec.data)
        except CredentialDecryptionError:
            logger.error("credential %s skipped during re-encryption (cannot decrypt)", rec.id)
            continue
        rec.data = encrypt_text(plaintext)
        count += 1
    db.commit()
    return count


def resolve_credentials(db: Session, user_id: int, refs: dict[str, str]) -> dict[str, Any]:
    """Decrypt the credentials referenced by a node's `credentials` map.

    `refs` maps credential type -> credential id. Returns
    `{type: decrypted_data}` for each ref; raises CredentialError on the
    first missing/foreign/undecryptable reference.
    """
    resolved: dict[str, Any] = {}
    for cred_type, cred_id in refs.items():
        rec = db.get(Credential, cred_id)
        if rec is None or rec.user_id != user_id:
            raise CredentialError(
                f"Credential '{cred_id}' for '{cred_type}' not found or not yours.",
                code="CREDENTIALS_REQUIRED",
            )
        if rec.type != cred_type:
            raise CredentialError(
                f"Credential '{rec.name}' is type '{rec.type}', expected '{cred_type}'.",
                code="CREDENTIALS_REQUIRED",
            )
        try:
            decrypted = json.loads(decrypt_text(rec.data))
            if isinstance(decrypted, dict):
                decrypted["_credential_id"] = cred_id
            resolved[cred_type] = decrypted
        except (CredentialDecryptionError, json.JSONDecodeError) as exc:
            logger.error("credential %s for user %s could not be decrypted", cred_id, user_id)
            raise CredentialError(
                f"Credential '{rec.name}' could not be decrypted.",
                code="CREDENTIALS_REQUIRED",
            ) from exc
    return resolved
