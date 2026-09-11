"""Auth-state persistence (auth fetch/store nodes).

One encrypted row per (workflow_id, provider). Reads are lock-free;
writes take SELECT FOR UPDATE so concurrent refreshes single-flight:
the loser re-reads the winner's fresh row instead of refreshing twice.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow_auth import WorkflowAuthState
from app.security.crypto import decrypt_text, encrypt_text

# Bundle keys persisted (encrypted). OAuth material rides along so the
# refresh adapter never needs a second lookup.
_BUNDLE_KEYS = (
    "access_token", "refresh_token", "token_type", "scope",
    "expires_at", "client_id", "client_secret", "token_url",
    "instance_url",
)


def _encode(bundle: dict[str, Any]) -> bytes:
    slim = {k: bundle.get(k) for k in _BUNDLE_KEYS if bundle.get(k) not in (None, "")}
    return encrypt_text(json.dumps(slim, ensure_ascii=False))


def _decode(row: WorkflowAuthState) -> dict[str, Any]:
    try:
        data = json.loads(decrypt_text(row.data))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_state(db: Session, workflow_id: str, provider: str) -> dict[str, Any] | None:
    """Lock-free read: decrypted bundle + row metadata, or None."""
    row = db.scalar(
        select(WorkflowAuthState).where(
            WorkflowAuthState.workflow_id == workflow_id,
            WorkflowAuthState.provider == provider,
        )
    )
    if row is None:
        return None
    return {
        **_decode(row),
        "_row_id": row.id,
        "_expires_at_column": row.expires_at.isoformat() if row.expires_at else None,
        "_updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _row_for_update(db: Session, workflow_id: str, provider: str) -> WorkflowAuthState | None:
    return db.scalar(
        select(WorkflowAuthState)
        .where(
            WorkflowAuthState.workflow_id == workflow_id,
            WorkflowAuthState.provider == provider,
        )
        .with_for_update()
    )


def upsert_state(
    db: Session,
    workflow_id: str,
    provider: str,
    bundle: dict[str, Any],
    *,
    expires_at: datetime | None = None,
    last_error: str = "",
) -> tuple[str, bool]:
    """Insert or replace the row under a row lock. Returns (row_id, created)."""
    row = _row_for_update(db, workflow_id, provider)
    created = row is None
    if created:
        row = WorkflowAuthState(
            id=f"was_{uuid.uuid4().hex[:12]}",
            workflow_id=workflow_id,
            provider=provider,
            data=_encode(bundle),
        )
        db.add(row)
    else:
        assert row is not None
        existing_bundle = _decode(row)
        merged_bundle = dict(bundle)
        for preserve_key in ("refresh_token", "client_id", "client_secret", "token_url", "token_type", "scope", "instance_url"):
            if not merged_bundle.get(preserve_key) and existing_bundle.get(preserve_key):
                merged_bundle[preserve_key] = existing_bundle[preserve_key]
        row.data = _encode(merged_bundle)
    row.expires_at = expires_at
    row.last_error = (last_error or "")[:500]
    db.commit()
    return row.id, created


def mark_validated(db: Session, workflow_id: str, provider: str) -> None:
    row = _row_for_update(db, workflow_id, provider)
    if row is None:
        return
    row.last_validated_at = datetime.now(UTC)
    row.last_error = ""
    db.commit()


def mark_failed(db: Session, workflow_id: str, provider: str, error: str) -> None:
    row = _row_for_update(db, workflow_id, provider)
    if row is None:
        return
    row.last_error = (error or "")[:500]
    db.commit()


async def locked_refresh(
    db: Session,
    workflow_id: str,
    provider: str,
    refresh,
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """Single-flight refresh under a row lock.

    Re-reads inside the lock (a concurrent execution may have refreshed
    first — then its bundle is returned untouched). Otherwise calls
    ``refresh(bundle)`` and persists the result. Returns the current
    bundle, or None when the row vanished.
    """
    from app.auth_state.adapter import is_expired, normalize_expires_at

    row = _row_for_update(db, workflow_id, provider)
    if row is None:
        return None
    bundle = _decode(row)
    if not force and not is_expired(normalize_expires_at(bundle.get("expires_at"))):
        return bundle
    new_bundle = await refresh(bundle)
    row.data = _encode(new_bundle)
    epoch = normalize_expires_at(new_bundle.get("expires_at"))
    row.expires_at = datetime.fromtimestamp(epoch, UTC) if epoch else None
    row.last_error = ""
    db.commit()
    return new_bundle
