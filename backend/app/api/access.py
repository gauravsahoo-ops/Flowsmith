"""Workflow access control (security phase): ownership + sharing.

Rules:
- owner: full access (view, edit, delete, run, share)
- edit share: view + edit + run, no delete/share
- view share: view only
- anyone else: 404 (existence is hidden)
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    OrganizationMember,
    User,
    Workspace,
    WorkspaceMember,
    WorkflowRecord,
    WorkflowShare,
)

PERMISSION_EDIT = "edit"
PERMISSION_VIEW = "view"
SHARE_PERMISSIONS = (PERMISSION_VIEW, PERMISSION_EDIT)


def workspace_can_view(db: Session, ws_id: str, user_id: int) -> bool:
    """View access to a workspace: creator, workspace member, or org member.

    Single source of truth for workspace membership (mirrors the historical
    ``workspaces._require_ws_member`` rules). Personal/absent workspaces
    (``ws is None``) grant nothing.
    """
    ws = db.get(Workspace, ws_id)
    if ws is None:
        return False
    if ws.creator_id == user_id:
        return True
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if member is not None:
        return True
    org_member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == ws.organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    return org_member is not None


def workspace_can_edit(db: Session, ws_id: str, user_id: int) -> bool:
    """Edit grant for a workspace: creator, member with edit rights, or
    org member with edit rights. Viewers and non-members get nothing."""
    ws = db.get(Workspace, ws_id)
    if ws is None:
        return False
    if ws.creator_id == user_id:
        return True
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if member is not None:
        return (member.role or "") in ("owner", "admin", "editor") or (member.permission or "") in ("edit", "admin")
    org_member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == ws.organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    if org_member is None:
        return False
    return (org_member.role or "") in ("owner", "admin", "founder") or (org_member.permission or "") in ("edit", "admin")


def permission_for_user_id(db: Session, workflow_id: str, user_id: int) -> str | None:
    """id-only mirror of ``get_permission`` (worker/tool contexts have no
    ``User`` object). Identical rules: owner, then explicit workflow share;
    soft-deleted workflows are invisible."""
    rec = db.get(WorkflowRecord, workflow_id)
    if rec is None or rec.deleted_at is not None:
        return None
    if rec.user_id == user_id:
        return "owner"
    share = db.scalar(
        select(WorkflowShare).where(
            WorkflowShare.workflow_id == workflow_id,
            WorkflowShare.user_id == user_id,
        )
    )
    return share.permission if share is not None else None


def get_permission(db: Session, workflow_id: str, user: User) -> str | None:
    """'owner' | 'edit' | 'view' | None (no access).

    Deleted (soft-deleted) workflows are invisible: None, so every
    caller 404s instead of seeing or mutating a dead workflow.
    """
    return permission_for_user_id(db, workflow_id, user.id)


def get_workflow(db: Session, workflow_id: str, user: User, *, require_edit: bool = False) -> WorkflowRecord:
    """Fetch a workflow the user may access; 404 hides existence."""
    permission = get_permission(db, workflow_id, user)
    if permission is None or (require_edit and permission == PERMISSION_VIEW):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    rec = db.get(WorkflowRecord, workflow_id)
    assert rec is not None
    return rec


def is_owner(db: Session, workflow_id: str, user: User) -> bool:
    return get_permission(db, workflow_id, user) == "owner"


def accessible_ids(db: Session, user: User) -> set[str]:
    """Ids of all workflows the user owns or can view (deleted excluded)."""
    owned = set(
        db.scalars(
            select(WorkflowRecord.id).where(
                WorkflowRecord.user_id == user.id,
                WorkflowRecord.deleted_at.is_(None),
            )
        ).all()
    )
    # Shared workflows: also check the parent workflow isn't soft-deleted
    shared = set(
        db.scalars(
            select(WorkflowShare.workflow_id)
            .join(WorkflowRecord, WorkflowShare.workflow_id == WorkflowRecord.id)
            .where(
                WorkflowShare.user_id == user.id,
                WorkflowRecord.deleted_at.is_(None),
            )
        ).all()
    )
    return owned | shared


def editable_ids(db: Session, user: User) -> set[str]:
    """Ids the user may edit (owner or edit share, deleted excluded)."""
    owned = set(
        db.scalars(
            select(WorkflowRecord.id).where(
                WorkflowRecord.user_id == user.id,
                WorkflowRecord.deleted_at.is_(None),
            )
        ).all()
    )
    shared = set(
        db.scalars(
            select(WorkflowShare.workflow_id)
            .join(WorkflowRecord, WorkflowShare.workflow_id == WorkflowRecord.id)
            .where(
                WorkflowShare.user_id == user.id,
                WorkflowShare.permission == PERMISSION_EDIT,
                WorkflowRecord.deleted_at.is_(None),
            )
        ).all()
    )
    return owned | shared


def batch_permissions(db: Session, workflow_ids: set[str], user: User) -> dict[str, str]:
    """Return {workflow_id: permission} for all given workflows in 2 queries
    instead of 2*N. Ownership is checked in Python (already in accessible_ids),
    shares are bulk-loaded."""
    if not workflow_ids:
        return {}
    # Owned workflows
    owned = set(
        db.scalars(
            select(WorkflowRecord.id).where(
                WorkflowRecord.id.in_(workflow_ids),
                WorkflowRecord.user_id == user.id,
                WorkflowRecord.deleted_at.is_(None),
            )
        ).all()
    )
    # Shared workflows
    shares = db.execute(
        select(WorkflowShare.workflow_id, WorkflowShare.permission).where(
            WorkflowShare.workflow_id.in_(workflow_ids),
            WorkflowShare.user_id == user.id,
        )
    ).all()
    result: dict[str, str] = {}
    for wf_id in owned:
        result[wf_id] = "owner"
    for wf_id, perm in shares:
        if wf_id not in result:  # owner takes precedence
            result[wf_id] = perm
    return result
