"""SCIM group resources and group-to-workspace membership mappings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ScimGroup(Base):
    """A SCIM group mapped to a private Flowsmith workspace."""

    __tablename__ = "scim_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    organization_permission: Mapped[str | None] = mapped_column(String(16), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("display_name", name="uq_scim_groups_display_name"),
        UniqueConstraint("workspace_id", name="uq_scim_groups_workspace_id"),
    )


class ScimGroupMember(Base):
    """A direct member of a SCIM group: a user or a child group."""

    __tablename__ = "scim_group_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("scim_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    member_group_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("scim_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_scim_group_member"),
        UniqueConstraint("group_id", "member_group_id", name="uq_scim_group_member_group"),
        {"sqlite_autoincrement": True},
    )


class ScimGroupAccess(Base):
    """Effective access materialized from direct and nested group members.

    One row per group/user pair. The created flags distinguish SCIM-managed
    workspace/organization memberships from memberships granted manually.
    """

    __tablename__ = "scim_group_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("scim_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_workspace_membership: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_organization_membership: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_scim_group_access"),
        {"sqlite_autoincrement": True},
    )
