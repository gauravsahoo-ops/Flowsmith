"""Organization CRUD API endpoints.

Provides list, create, get, update, delete for organizations.
Members can be added/removed from organizations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.audit import log_event
from app.db import get_db
from app.models import (
    Environment,
    FileRecord,
    Organization,
    OrganizationMember,
    RagCollection,
    Subscription,
    User,
    WebAuthnCredential,
    WorkflowRecord,
    Workspace,
    WorkspaceMember,
)

router = APIRouter()

ORG_CREATED = "organization.created"
ORG_UPDATED = "organization.updated"
ORG_DELETED = "organization.deleted"
ORG_MEMBER_ADDED = "organization.member_added"
ORG_MEMBER_REMOVED = "organization.member_removed"


class OrganizationCreate(BaseModel):
    name: str
    description: str = ""


class OrganizationUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_public: bool | None = None
    require_mfa: bool | None = None


class MemberAdd(BaseModel):
    user_id: int
    role: str = "member"
    permission: str = "view"


class MemberUpdate(BaseModel):
    role: str | None = None
    permission: str | None = None


def _require_org_owner(db: Session, org_id: str, user: User) -> Organization:
    """Return org if user is owner/founder, else 404/403."""
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    if org.founder_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the organization founder can perform this action.")
    return org


@router.get("/api/organizations")
def list_organizations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """List organizations the user belongs to or that are public."""
    page, size = page_params(1, 50)
    stmt = select(Organization).where(
        (Organization.is_public == True) | (Organization.id.in_(
            select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user.id)
        ))
    ).order_by(Organization.created_at.desc()).offset((page - 1) * size).limit(size)
    orgs = db.execute(stmt).scalars().all()
    return ok([{
        "id": o.id,
        "name": o.name,
        "description": o.description,
        "founder_id": o.founder_id,
        "is_public": o.is_public,
        "require_mfa": bool(o.require_mfa),
        "created_at": str(o.created_at),
    } for o in orgs])


@router.post("/api/organizations")
def create_organization(payload: OrganizationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Create a new organization. Creator becomes the founder."""
    existing = db.execute(
        select(Organization).where(Organization.name == payload.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Organization name already taken.")
    org_id = f"org_{uuid.uuid4().hex[:12]}"
    org = Organization(
        id=org_id,
        name=payload.name,
        description=payload.description,
        founder_id=user.id,
    )
    db.add(org)
    # Add founder as admin member
    member = OrganizationMember(
        organization_id=org_id,
        user_id=user.id,
        role="admin",
        permission="admin",
    )
    db.add(member)
    db.commit()
    log_event(db, ORG_CREATED, target_type="organization", target_id=org_id, user_id=user.id)
    return ok({"id": org_id, "name": org.name})


@router.get("/api/organizations/{org_id}")
def get_organization(org_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Get organization details."""
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    if not org.is_public:
        # Check membership
        is_member = db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        ).scalar_one_or_none()
        if is_member is None and org.founder_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    return ok({
        "id": org.id,
        "name": org.name,
        "description": org.description,
        "founder_id": org.founder_id,
        "is_public": org.is_public,
        "require_mfa": bool(org.require_mfa),
        "created_at": str(org.created_at),
    })


@router.patch("/api/organizations/{org_id}")
def update_organization(org_id: str, payload: OrganizationUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Update organization settings (founder only)."""
    org = _require_org_owner(db, org_id, user)
    if payload.name is not None:
        org.name = payload.name
    if payload.description is not None:
        org.description = payload.description
    if payload.is_public is not None:
        org.is_public = payload.is_public
    if payload.require_mfa is not None:
        was_required = bool(org.require_mfa)
        org.require_mfa = payload.require_mfa
        if payload.require_mfa and not was_required:
            # Enabling the policy invalidates existing bearer tokens for the
            # organization's users so the next request forces a login and the
            # enrollment flow. Disabling the policy does not revoke sessions.
            member_ids = select(OrganizationMember.user_id).where(
                OrganizationMember.organization_id == org_id
            )
            db.execute(
                update(User)
                .where(
                    or_(User.organization_id == org_id, User.id.in_(member_ids)),
                    User.mfa_enabled.is_not(True),
                    ~User.id.in_(select(WebAuthnCredential.user_id)),
                )
                .values(tokens_valid_from=datetime.now(UTC))
            )
    db.commit()
    log_event(
        db,
        ORG_UPDATED,
        target_type="organization",
        target_id=org_id,
        user_id=user.id,
        detail={"require_mfa": bool(org.require_mfa)},
    )
    return ok({
        "id": org.id,
        "name": org.name,
        "require_mfa": bool(org.require_mfa),
    })


@router.delete("/api/organizations/{org_id}")
def delete_organization(org_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Delete an organization (founder only).

    Refuses to delete while its workspaces still contain workflows: those
    rows own credentials, versions, and execution history that must not be
    destroyed implicitly. Empty workspaces, subscriptions, and memberships
    are cleaned up with the organization.
    """
    org = _require_org_owner(db, org_id, user)
    ws_ids = list(
        db.scalars(select(Workspace.id).where(Workspace.organization_id == org_id)).all()
    )
    if ws_ids:
        workflow_count = db.scalar(
            select(func.count())
            .select_from(WorkflowRecord)
            .where(WorkflowRecord.workspace_id.in_(ws_ids))
        ) or 0
        if workflow_count:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Delete or move the organization's workflows before deleting it.",
            )
        # Users may still point at a workspace/org directly (legacy fields).
        db.execute(
            update(User)
            .where(User.workspace_id.in_(ws_ids))
            .values(workspace_id=None)
        )
        db.execute(
            update(FileRecord)
            .where(FileRecord.workspace_id.in_(ws_ids))
            .values(workspace_id=None)
        )
        db.execute(
            update(RagCollection)
            .where(RagCollection.workspace_id.in_(ws_ids))
            .values(workspace_id=None)
        )
        db.execute(delete(Environment).where(Environment.workspace_id.in_(ws_ids)))
    db.execute(update(User).where(User.organization_id == org_id).values(organization_id=None))
    db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id.in_(ws_ids)))
    db.execute(delete(Workspace).where(Workspace.organization_id == org_id))
    db.execute(delete(Subscription).where(Subscription.organization_id == org_id))
    db.query(OrganizationMember).where(OrganizationMember.organization_id == org_id).delete()
    db.delete(org)
    db.commit()
    log_event(db, ORG_DELETED, target_type="organization", target_id=org_id, user_id=user.id)
    return ok({"deleted": True})


@router.get("/api/organizations/{org_id}/members")
def list_members(org_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """List organization members (members only; 404 hides existence)."""
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    if org.founder_id != user.id:
        member = db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user.id,
            )
        )
        if member is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found.")
    members = db.execute(
        select(OrganizationMember).where(OrganizationMember.organization_id == org_id)
    ).scalars().all()
    return ok([{
        "user_id": m.user_id,
        "role": m.role,
        "permission": m.permission,
        "joined_at": str(m.joined_at),
    } for m in members])


@router.post("/api/organizations/{org_id}/members")
def add_member(org_id: str, payload: MemberAdd, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Add a member to the organization (founder/admin only)."""
    org = _require_org_owner(db, org_id, user)
    # Check if user exists
    target_user = db.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    # Check if already a member
    existing = db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == payload.user_id,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a member.")
    member = OrganizationMember(
        organization_id=org_id,
        user_id=payload.user_id,
        role=payload.role,
        permission=payload.permission,
    )
    db.add(member)
    db.commit()
    log_event(db, ORG_MEMBER_ADDED, target_type="organization", target_id=org_id, user_id=user.id,
              detail={"member_user_id": payload.user_id})
    return ok({"user_id": payload.user_id, "role": payload.role})


@router.delete("/api/organizations/{org_id}/members/{member_user_id}")
def remove_member(org_id: str, member_user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Remove a member from the organization (founder/admin only)."""
    org = _require_org_owner(db, org_id, user)
    member = db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == member_user_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    db.delete(member)
    db.commit()
    log_event(db, ORG_MEMBER_REMOVED, target_type="organization", target_id=org_id, user_id=user.id,
              detail={"member_user_id": member_user_id})
    return ok({"deleted": True})
