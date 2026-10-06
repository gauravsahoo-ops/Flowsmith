"""Organization and Workspace models (multi-tenancy, spec 38+).

Allows organizing users into organizations, and workflows into workspaces
within organizations. Supports isolation of data while allowing cross-
workspace collaboration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import Organization, User, WorkflowRecord

class Organization(Base):
    """Organization (company/team) container for users and workflows."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # The user who founded/created the organization. Plain column (no FK):
    # organizations <-> users would create an unresolvable FK cycle that
    # breaks SQLAlchemy's flush ordering (users.organization_id points
    # back at organizations).
    founder_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    # Whether the organization is public or private
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrganizationMember(Base):
    """Membership of a user in an organization with a role."""

    __tablename__ = "organization_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    # Permissions within the organization: view, edit, admin
    permission: Mapped[str] = mapped_column(String(16), default="view", nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Declared so the unit of work orders inserts by FK dependency.
    organization: Mapped["Organization"] = relationship()
    user: Mapped["User"] = relationship()

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        {"sqlite_autoincrement": True},
    )


class Workspace(Base):
    """Workspace (project/team) within an organization.

    A workflow belongs to exactly one workspace. Workflows can be shared
    across workspaces via organization membership.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id"), index=True, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, default="")
    # The workspace creator/owner. Plain column (no FK): same cycle
    # rationale as organizations.founder_id.
    creator_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    # Whether the workspace is private (only members can see/access)
    is_private: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Declared so the unit of work orders inserts by FK dependency.
    organization: Mapped["Organization"] = relationship()


class WorkspaceMember(Base):
    """Membership of a user in a workspace with a role."""

    __tablename__ = "workspace_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workspaces.id"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    permission: Mapped[str] = mapped_column(String(16), default="view", nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Declared so the unit of work orders inserts by FK dependency.
    workspace: Mapped["Workspace"] = relationship()
    user: Mapped["User"] = relationship()

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_ws_member"),
        {"sqlite_autoincrement": True},
    )


class WorkflowVersionRecord(Base):
    """Immutable snapshot of a workflow version.

    Each row represents a frozen version of a workflow. The combination
    of (workflow_id, version) is unique. When a workflow is saved, a new
    row is created rather than updating an existing one (spec 24.2/24.3).
    """

    __tablename__ = "workflow_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workflows.id"), index=True, nullable=False
    )
    # The workspace this version belongs to (spec 38)
    workspace_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("workspaces.id"), index=True, nullable=True
    )
    # The workflow this version belongs to (the "parent" workflow name/id)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Snapshot of the workflow JSON at the time this version was created
    data: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    # The user who created this version
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # Whether this is the currently active version
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # When this version was created
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Declared so the unit of work orders inserts by FK dependency.
    workflow: Mapped["WorkflowRecord"] = relationship()
    workspace: Mapped["Workspace | None"] = relationship()
    user: Mapped["User"] = relationship()

    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
    )
