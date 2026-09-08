"""CredentialStore — secure storage abstraction."""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.credential import Credential
from app.security.crypto import decrypt_text, encrypt_text
from .schema_registry import get_schema_registry


class CredentialStore:
    """Wraps Credential persistence with encryption.

    Workflow JSON stores only credentialId + credentialType,
    never secrets. Secrets are encrypted at rest via Fernet.
    """

    def list_for_user(self, db: Session, user_id: int) -> List[Dict[str, str]]:
        from sqlalchemy import select
        recs = db.scalars(select(Credential).where(Credential.user_id == user_id).order_by(Credential.created_at.desc())).all()
        return [{"id": r.id, "name": r.name, "type": r.type} for r in recs]

    def create(self, db: Session, user_id: int, name: str, cred_type: str, data: Dict[str, Any]) -> Dict[str, str]:
        registry = get_schema_registry()
        normalized = registry.validate(cred_type, data)
        blob = encrypt_text(json.dumps(normalized, ensure_ascii=False))
        rec = Credential(id=f"cred_{uuid.uuid4().hex[:12]}", user_id=user_id, name=name, type=cred_type, data=blob)
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return {"id": rec.id, "name": rec.name, "type": rec.type}

    def delete(self, db: Session, user_id: int, credential_id: str) -> None:
        from app.credentials.service import CredentialError
        rec = db.get(Credential, credential_id)
        if rec is None or rec.user_id != user_id:
            raise CredentialError("Credential not found.", code="CREDENTIAL_NOT_FOUND")
        db.delete(rec)
        db.commit()

    def get_encrypted(self, db: Session, user_id: int, credential_id: str) -> Credential:
        from app.credentials.service import CredentialError
        rec = db.get(Credential, credential_id)
        if rec is None or rec.user_id != user_id:
            raise CredentialError(f"Credential '{credential_id}' not found.", code="CREDENTIAL_NOT_FOUND")
        return rec

    def decrypt(self, rec: Credential) -> Dict[str, Any]:
        raw = decrypt_text(rec.data)
        return json.loads(raw)


_credential_store = CredentialStore()


def get_credential_store() -> CredentialStore:
    return _credential_store
