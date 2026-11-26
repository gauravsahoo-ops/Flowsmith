"""Workflow access control (security phase): ownership + sharing.

Rules:
- owner: full access (view, edit, delete, run, share)
- edit share: view + edit + run, no delete/share
- view share: view only
- anyone else: 404 (existence is hidden)
"""

from __future__ import annotations

from typing import Any

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
ORG_ADMIN_ROLES = frozenset({"owner", "admin", "founder"})


def user_organization_id(db: Session, user: User) -> str | None:
    """Primary organization for account-scoped settings.

    ``users.organization_id`` is authoritative. Legacy rows fall back to the
    organization of their default workspace, then to their first membership
    (locally registered accounts get a personal organization at signup).
    """
    if user.organization_id:
        return user.organization_id
    if user.workspace_id:
        workspace = db.get(Workspace, user.workspace_id)
        if workspace is not None:
            return workspace.organization_id
    membership_org = db.scalar(
        select(OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(OrganizationMember.id)
    )
    return membership_org


def organization_roles(db: Session, user: User) -> set[str]:
    """Role and permission strings the user holds in their primary org."""
    org_id = user_organization_id(db, user)
    if not org_id:
        return set()
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if member is None:
        return set()
    return {(member.role or "").lower(), (member.permission or "").lower()}


def is_organization_admin(db: Session, user: User) -> bool:
    return bool(organization_roles(db, user) & ORG_ADMIN_ROLES)


def require_organization_admin(db: Session, user: User) -> str:
    """Return the caller's organization id or raise 400/403."""
    org_id = user_organization_id(db, user)
    if not org_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An organization is required to change account settings.",
        )
    if not is_organization_admin(db, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Organization owner or admin access is required.",
        )
    return org_id


def organization_user_ids(db: Session, user: User) -> set[int]:
    """Ids visible in the caller's organization scope.

    A user with no organization sees only their own account. The query also
    includes users whose primary ``organization_id`` points at the org but
    whose membership row is missing (legacy imports).
    """
    org_id = user_organization_id(db, user)
    if not org_id:
        return {user.id}
    member_ids = set(
        db.scalars(
            select(OrganizationMember.user_id).where(
                OrganizationMember.organization_id == org_id
            )
        ).all()
    )
    primary_ids = set(
        db.scalars(select(User.id).where(User.organization_id == org_id)).all()
    )
    return (member_ids | primary_ids) or {user.id}


def validate_connector_ownership(
    db: Session, user_id: int, nodes: Any
) -> None:
    """Reject nodes that use a generated connector owned by another account."""
    from app.models import GeneratedConnector

    hidden = set(
        db.scalars(
            select(GeneratedConnector.connector_key).where(
                GeneratedConnector.user_id != user_id
            )
        ).all()
    )
    if not hidden:
        return
    for node in nodes or []:
        node_type = (
            node.get("type") if isinstance(node, dict) else getattr(node, "type", None)
        )
        if node_type in hidden:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Workflow references a connector owned by another account.",
            )


def require_instance_admin(user: User) -> User:
    """Guard global infrastructure actions (packs, maintenance, registry)."""
    if (user.role or "").lower() != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Instance administrator access is required.",
        )
    return user


def workspace_can_view(db: Session, ws_id: str, user_id: int) -> bool:
    """View access to a workspace.

    The creator and explicit workspace members always have access. Other
    members of the owning organization only see the workspace when it is
    not private (``is_private``). Personal/absent workspaces grant nothing.
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
    if ws.is_private:
        return False
    org_member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == ws.organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
    return org_member is not None


def workspace_can_edit(db: Session, ws_id: str, user_id: int) -> bool:
    """Edit grant for a workspace.

    The creator and explicit workspace members with edit rights always win.
    Organization-level edit grants apply only to non-private workspaces.
    Viewers and non-members get nothing.
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
        return (member.role or "") in ("owner", "admin", "editor") or (member.permission or "") in ("edit", "admin")
    if ws.is_private:
        return False
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


def get_workflow(
    db: Session,
    workflow_id: str,
    user: User,
    *,
    require_edit: bool = False,
    for_update: bool = False,
) -> WorkflowRecord:
    """Fetch a workflow the user may access; 404 hides existence.

    ``for_update`` takes a row lock so a read-modify-write sequence
    (notably workflow save/version bumping) is serialized across workers.
    """
    permission = get_permission(db, workflow_id, user)
    if permission is None or (require_edit and permission == PERMISSION_VIEW):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    if for_update:
        rec = db.scalar(
            select(WorkflowRecord)
            .where(WorkflowRecord.id == workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    else:
        rec = db.get(WorkflowRecord, workflow_id)
    if rec is None or rec.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    return rec


def is_owner(db: Session, workflow_id: str, user: User) -> bool:
    return get_permission(db, workflow_id, user) == "owner"


def owned_ids(db: Session, user: User) -> set[str]:
    """Ids of workflows the user owns (deleted excluded)."""
    return set(
        db.scalars(
            select(WorkflowRecord.id).where(
                WorkflowRecord.user_id == user.id,
                WorkflowRecord.deleted_at.is_(None),
            )
        ).all()
    )


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
