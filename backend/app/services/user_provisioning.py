"""Shared user-scope provisioning helpers.

SCIM and enterprise SSO both need to place newly provisioned users into an
organization and workspace. Keep the validation and membership creation in one
place so the two provisioning paths cannot drift.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMember, User, Workspace, WorkspaceMember


def resolve_scope(
    db: Session, organization_id: str, workspace_id: str
) -> tuple[str | None, str | None]:
    """Validate and normalize an organization/workspace pair."""
    org_id = str(organization_id or "").strip() or None
    ws_id = str(workspace_id or "").strip() or None
    if org_id and db.get(Organization, org_id) is None:
        raise ValueError(f"Organization '{org_id}' does not exist.")
    if ws_id:
        workspace = db.get(Workspace, ws_id)
        if workspace is None:
            raise ValueError(f"Workspace '{ws_id}' does not exist.")
        if org_id and workspace.organization_id != org_id:
            raise ValueError("The workspace does not belong to the configured organization.")
        org_id = org_id or workspace.organization_id
    return org_id, ws_id


def apply_default_scope(
    db: Session,
    user: User,
    organization_id: str,
    workspace_id: str,
    *,
    member_role: str = "member",
    permission: str = "edit",
) -> None:
    """Attach a user to the configured default organization/workspace.

    The caller is responsible for flushing ``user`` first so ``user.id`` is
    available. Missing membership rows are created; existing rows are left
    untouched.
    """
    org_id, ws_id = resolve_scope(db, organization_id, workspace_id)
    user.organization_id = org_id
    user.workspace_id = ws_id
    if org_id:
        member = db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        )
        if member is None:
            db.add(OrganizationMember(
                organization_id=org_id,
                user_id=user.id,
                role=member_role,
                permission=permission,
            ))
    if ws_id:
        member = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws_id,
                WorkspaceMember.user_id == user.id,
            )
        )
        if member is None:
            db.add(WorkspaceMember(
                workspace_id=ws_id,
                user_id=user.id,
                role=member_role,
                permission=permission,
            ))
