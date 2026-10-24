"""User account model (spec 5: users).

`role` is admin | member (first registered account becomes admin);
`active` gates login and token use (deactivated accounts are locked out).
`organization_id` and `workspace_id` gate workspace-scoped access
(spec 38: multi-tenancy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import Organization, Workspace

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Multi-tenancy fields (spec 38)
    organization_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.id"), index=True, nullable=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("workspaces.id"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Tokens issued before this instant are rejected (set on password reset so
    # a stolen bearer token dies with the old password).
    tokens_valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # TOTP MFA. The secret is Fernet-encrypted at rest; mfa_last_step is the
    # last accepted 30-second counter, used to reject replay of a used code.
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    mfa_secret: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    mfa_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # SHA-256 hashes of one-time recovery codes (never the plaintext codes).
    mfa_recovery_hashes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Last LDAP identity observed at login, used by background group sync.
    ldap_dn: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    ldap_groups: Mapped[str | None] = mapped_column(Text, nullable=True)
    ldap_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # Declared so the unit of work orders inserts by FK dependency.
    organization: Mapped["Organization | None"] = relationship()
    workspace: Mapped["Workspace | None"] = relationship()
