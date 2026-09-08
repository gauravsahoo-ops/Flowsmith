"""Runtime environment-variable resolution (Phase 31).

Workspace-scoped environment variables (``environments`` table) are the
per-workspace configuration layer of the platform: API base URLs, feature
flags and secrets that workflows reference via ``{{ $env.KEY }}``
expressions. Values are encrypted at rest with the same Fernet keyring as
credentials (spec 12/29) and are decrypted only here — at execution time,
inside the worker — never in API responses (secret values are masked) and
never in traces or logs.

Workers are stateless (spec 34): they resolve the variables for a job's
workspace from PostgreSQL at job start; nothing is cached across jobs.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Environment
from app.security.crypto import CredentialDecryptionError, decrypt_text

logger = logging.getLogger("environments")

# Legacy rows written before Phase 31 stored plaintext. They still
# resolve (backward compatibility); new/updated values are always
# encrypted tokens with the `k{idx}:` prefix.
_PREFIX = "k"


def decrypt_env_value(stored: str) -> str:
    """Best-effort decryption of a stored env value.

    Encrypted values look like ``k0:<fernet-token>``. Anything that does
    not decrypt is returned verbatim so legacy plaintext keeps working.
    """
    if not stored.startswith(_PREFIX):
        return stored
    try:
        return decrypt_text(stored.encode())
    except (CredentialDecryptionError, ValueError):
        return stored


def resolve_env_vars(db: Session, workspace_id: str | None) -> dict[str, str]:
    """Decrypted {key: value} map for a workspace ({} without one)."""
    if not workspace_id:
        return {}
    rows = db.scalars(
        select(Environment).where(Environment.workspace_id == workspace_id)
    ).all()
    out: dict[str, str] = {}
    for row in rows:
        try:
            out[row.key] = decrypt_env_value(row.value)
        except Exception:  # never break an execution over one bad row
            logger.exception("failed to resolve environment variable %s", row.key)
    return out
