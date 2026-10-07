"""User account model (spec 5: users).

`role` is admin | member (first registered account becomes admin);
`active` gates login and token use (deactivated accounts are locked out).
`organization_id` and `workspace_id` gate workspace-scoped access
(spec 38: multi-tenancy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, ForeignKey, func
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

    # Declared so the unit of work orders inserts by FK dependency.
    organization: Mapped["Organization | None"] = relationship()
    workspace: Mapped["Workspace | None"] = relationship()
