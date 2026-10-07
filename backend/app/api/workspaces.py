"""Workspace CRUD API endpoints.

Provides list, create, get, update, delete for workspaces.
Workspaces belong to an organization and contain workflows.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.audit import log_event
from app.db import get_db
from app.models import Organization, OrganizationMember, User, WorkflowRecord, Workspace, WorkspaceMember

router = APIRouter()

WS_CREATED = "workspace.created"
WS_UPDATED = "workspace.updated"
WS_DELETED = "workspace.deleted"
WS_MEMBER_ADDED = "workspace.member_added"
WS_MEMBER_REMOVED = "workspace.member_removed"


class WorkspaceCreate(BaseModel):
    name: str
    organization_id: str
    description: str = ""
    is_private: bool = True


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_private: bool | None = None


class WSMemberAdd(BaseModel):
    user_id: int
    role: str = "member"


def _require_ws_owner(db: Session, ws_id: str, user: User) -> Workspace:
    ws = db.get(Workspace, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    if ws.creator_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the workspace creator can perform this action.")
    return ws


def _require_ws_member(db: Session, ws_id: str, user: User) -> bool:
    """Return True if user has view access to the workspace.

    Rules live in ``app.api.access.workspace_can_view`` (creator, member,
    or org member); this wrapper only adds the workspace-exists 404.
    """
    from app.api.access import workspace_can_view

    if db.get(Workspace, ws_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return workspace_can_view(db, ws_id, user.id)


def ensure_personal_workspace(db: Session, user: User) -> Workspace:
    """Ensure a default Personal workspace exists for this user."""
    ws_id = f"ws_personal_{user.id}"
    ws = db.get(Workspace, ws_id)
    if ws is not None:
        return ws
    org_id = f"org_personal_{user.id}"
    org = db.get(Organization, org_id)
    if org is None:
        org = Organization(
            id=org_id,
            name=f"Personal ({user.email or user.id})",
            founder_id=user.id,
            is_public=False,
        )
        db.add(org)
        db.flush()
        db.add(OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role="admin",
            permission="admin",
        ))
    ws = Workspace(
        id=ws_id,
        name="Personal",
        description="Default personal workspace",
        organization_id=org.id,
        creator_id=user.id,
        is_private=True,
    )
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(
        workspace_id=ws.id,
        user_id=user.id,
        role="admin",
        permission="edit",
    ))
    db.commit()
    return ws


@router.get("/api/workspaces")
def list_workspaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """List workspaces the user has access to."""
    ensure_personal_workspace(db, user)
    page, size = page_params(1, 50)
    # Get workspaces created by user
    created = select(Workspace.id).where(Workspace.creator_id == user.id)
    # Get workspaces where user is a member
    member_of = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
    # Get workspaces in user's organizations
    org_ws = select(Workspace.id).join(
        Organization, Workspace.organization_id == Organization.id
    ).join(
        OrganizationMember, OrganizationMember.organization_id == Organization.id
    ).where(OrganizationMember.user_id == user.id)

    stmt = select(Workspace).where(
        Workspace.id.in_(created.union(member_of, org_ws))
    ).order_by(Workspace.created_at.desc()).offset((page - 1) * size).limit(size)
    workspaces = db.execute(stmt).scalars().all()
    return ok([{
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "organization_id": w.organization_id,
        "creator_id": w.creator_id,
        "is_private": w.is_private,
        "created_at": str(w.created_at),
    } for w in workspaces])


@router.post("/api/workspaces")
def create_workspace(payload: WorkspaceCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Create a new workspace within an organization."""
    # Verify organization exists and user is a member
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    is_org_member = db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == payload.organization_id,
            OrganizationMember.user_id == user.id,
        )
    ).scalar_one_or_none()
    if is_org_member is None and org.founder_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this organization.")

    # Check for duplicate name in same org
    existing = db.execute(
        select(Workspace).where(
            Workspace.organization_id == payload.organization_id,
            Workspace.name == payload.name,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workspace name already taken in this organization.")

    ws_id = f"ws_{uuid.uuid4().hex[:12]}"
    ws = Workspace(
        id=ws_id,
        name=payload.name,
        description=payload.description,
        organization_id=payload.organization_id,
        creator_id=user.id,
        is_private=payload.is_private,
    )
    db.add(ws)
    # Add creator as admin member
    member = WorkspaceMember(
        workspace_id=ws_id,
        user_id=user.id,
        role="admin",
    )
    db.add(member)
    db.commit()
    log_event(db, WS_CREATED, target_type="workspace", target_id=ws_id, user_id=user.id)
    return ok({"id": ws_id, "name": ws.name})


@router.get("/api/workspaces/{ws_id}")
def get_workspace(ws_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Get workspace details."""
    ws = db.get(Workspace, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    if not _require_ws_member(db, ws_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return ok({
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "organization_id": ws.organization_id,
        "creator_id": ws.creator_id,
        "is_private": ws.is_private,
        "created_at": str(ws.created_at),
    })


@router.patch("/api/workspaces/{ws_id}")
def update_workspace(ws_id: str, payload: WorkspaceUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Update workspace settings (owner only)."""
    ws = _require_ws_owner(db, ws_id, user)
    if payload.name is not None:
        ws.name = payload.name
    if payload.description is not None:
        ws.description = payload.description
    if payload.is_private is not None:
        ws.is_private = payload.is_private
    db.commit()
    log_event(db, WS_UPDATED, target_type="workspace", target_id=ws_id, user_id=user.id)
    return ok({"id": ws.id, "name": ws.name})


@router.delete("/api/workspaces/{ws_id}")
def delete_workspace(ws_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Delete a workspace (owner only). Cannot delete if workflows exist."""
    ws = _require_ws_owner(db, ws_id, user)
    # Check for active workflows
    wf_count = len(db.execute(
        select(WorkflowRecord.id).where(WorkflowRecord.workspace_id == ws_id, WorkflowRecord.deleted_at.is_(None))
    ).fetchall())
    if wf_count > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot delete workspace with active workflows. Move or delete them first.")
    # Remove all members
    db.query(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id).delete()
    db.delete(ws)
    db.commit()
    log_event(db, WS_DELETED, target_type="workspace", target_id=ws_id, user_id=user.id)
    return ok({"deleted": True})


@router.get("/api/workspaces/{ws_id}/workflows")
def list_workspace_workflows(ws_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """List workflows in a workspace."""
    if not _require_ws_member(db, ws_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    page, size = page_params(1, 50)
    stmt = select(WorkflowRecord).where(
        WorkflowRecord.workspace_id == ws_id,
        WorkflowRecord.deleted_at.is_(None),
    ).order_by(WorkflowRecord.updated_at.desc()).offset((page - 1) * size).limit(size)
    workflows = db.execute(stmt).scalars().all()
    return ok([{
        "id": w.id,
        "name": w.name,
        "active": w.active,
        "node_count": len((w.data or {}).get("nodes", [])),
        "created_at": str(w.created_at),
        "updated_at": str(w.updated_at),
    } for w in workflows])


@router.get("/api/workspaces/{ws_id}/members")
def list_ws_members(ws_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """List workspace members (members only; 404 hides existence)."""
    if not _require_ws_member(db, ws_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    members = db.execute(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws_id)
    ).scalars().all()
    return ok([{
        "user_id": m.user_id,
        "role": m.role,
        "joined_at": str(m.joined_at),
    } for m in members])


@router.post("/api/workspaces/{ws_id}/members")
def add_ws_member(ws_id: str, payload: WSMemberAdd, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Add a member to the workspace (owner/admin only)."""
    ws = _require_ws_owner(db, ws_id, user)
    target_user = db.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    existing = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws_id,
            WorkspaceMember.user_id == payload.user_id,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a member.")
    member = WorkspaceMember(
        workspace_id=ws_id,
        user_id=payload.user_id,
        role=payload.role,
    )
    db.add(member)
    db.commit()
    log_event(db, WS_MEMBER_ADDED, target_type="workspace", target_id=ws_id, user_id=user.id,
              detail={"member_user_id": payload.user_id})
    return ok({"user_id": payload.user_id, "role": payload.role})


@router.delete("/api/workspaces/{ws_id}/members/{member_user_id}")
def remove_ws_member(ws_id: str, member_user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Remove a member from the workspace (owner only)."""
    ws = _require_ws_owner(db, ws_id, user)
    member = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws_id,
            WorkspaceMember.user_id == member_user_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    db.delete(member)
    db.commit()
    log_event(db, WS_MEMBER_REMOVED, target_type="workspace", target_id=ws_id, user_id=user.id,
              detail={"member_user_id": member_user_id})
    return ok({"deleted": True})
