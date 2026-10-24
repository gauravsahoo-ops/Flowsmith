"""Identity-provider group access mappings.

SCIM has its own group/workspace model. LDAP and SAML can additionally map
directory groups to workspace memberships; this table records which workspace
members the identity provider created so removing a group does not delete a
manually granted membership.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IdentityGroupAccess(Base):
    __tablename__ = "identity_group_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    permission: Mapped[str] = mapped_column(String(16), nullable=False, default="edit")
    created_workspace_membership: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "source", "group_name", "workspace_id",
            name="uq_identity_group_access",
        ),
        {"sqlite_autoincrement": True},
    )
