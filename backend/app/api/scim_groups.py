"""SCIM 2.0 group provisioning mapped to private Flowsmith workspaces.

A SCIM group is materialized as a private workspace inside the configured
organization. Group membership is mirrored into WorkspaceMember rows, so IdP
group changes actually grant and revoke workflow access instead of only
storing metadata.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.scim import (
    _MAX_RESULTS,
    _base_url,
    _require_scim,
    _resource_meta,
    _scim_error,
    _scim_json,
)
from app.audit import SCIM_GROUP_CREATE, SCIM_GROUP_DELETE, SCIM_GROUP_UPDATE, log_event
from app.config import get_settings
from app.db import get_db
from app.models import (
    Organization,
    OrganizationMember,
    ScimGroup,
    ScimGroupAccess,
    ScimGroupMember,
    User,
    Workspace,
    WorkspaceMember,
)

router = APIRouter(prefix="/scim/v2", tags=["scim"])

_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
_GROUP_EXTENSION = "urn:flowsmith:params:scim:schemas:extension:group:2.0:Group"
_GROUP_FILTER_RE = re.compile(
    r'^\s*(displayName|externalId|id)\s+eq\s+(?:"([^"]*)"|([^\s]+))\s*$',
    re.IGNORECASE,
)
_MEMBER_PATH_RE = re.compile(r'^members\[value\s+eq\s+"?([^"\]]+)"?\]$', re.IGNORECASE)


def _display_name(body: dict[str, Any]) -> str:
    value = body.get("displayName")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("displayName is required.")
    value = value.strip()
    if len(value) > 255:
        raise ValueError("displayName is too long.")
    return value


def _external_id(body: dict[str, Any]) -> str | None:
    value = body.get("externalId")
    if value is None:
        return None
    text = str(value).strip()
    return text[:255] if text else None


def _organization_attributes(body: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = body.get(_GROUP_EXTENSION)
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        raise ValueError("The group organization extension must be an object.")
    role = str(raw.get("organizationRole") or "").strip().lower() or None
    permission = str(raw.get("organizationPermission") or "").strip().lower() or None
    if role is None and permission is None:
        return None, None
    if role not in ("admin", "member"):
        raise ValueError("organizationRole must be 'admin' or 'member'.")
    if permission is not None and permission not in ("view", "edit", "admin"):
        raise ValueError("organizationPermission must be view, edit, or admin.")
    if permission is None:
        permission = "admin" if role == "admin" else "view"
    return role, permission


def _member_refs(
    db: Session, members: Any, *, parent_group_id: str | None = None
) -> tuple[set[int], set[str]]:
    if members is None:
        return set(), set()
    if not isinstance(members, list):
        raise ValueError("members must be an array.")
    user_ids: set[int] = set()
    child_group_ids: set[str] = set()
    for member in members:
        raw = member.get("value") if isinstance(member, dict) else member
        member_type = str(member.get("type") or "").lower() if isinstance(member, dict) else ""
        raw_text = str(raw or "").strip()
        if not raw_text:
            raise ValueError("Each group member must have a value.")
        group = db.get(ScimGroup, raw_text)
        if member_type == "group" or (group is not None and not raw_text.isdigit()):
            if group is None or not group.active:
                raise ValueError(f"SCIM child group {raw_text} does not exist.")
            if parent_group_id and group.id == parent_group_id:
                raise ValueError("A SCIM group cannot contain itself.")
            if parent_group_id:
                parent = db.get(ScimGroup, parent_group_id)
                parent_workspace = _workspace_for_group(db, parent) if parent else None
                child_workspace = _workspace_for_group(db, group)
                if (
                    parent_workspace is not None
                    and child_workspace.organization_id != parent_workspace.organization_id
                ):
                    raise ValueError("Nested SCIM groups must belong to the same organization.")
            child_group_ids.add(group.id)
            continue
        try:
            user_id = int(raw_text)
        except ValueError as exc:
            raise ValueError("Each user group member must have an integer value.") from exc
        if db.get(User, user_id) is None:
            raise ValueError(f"SCIM group member {user_id} does not exist.")
        user_ids.add(user_id)
    return user_ids, child_group_ids


def _get_group(db: Session, group_id: str) -> ScimGroup | None:
    group = db.get(ScimGroup, group_id)
    if group is None or not group.active:
        return None
    return group


def _group_organization(db: Session) -> str:
    settings = get_settings()
    org_id = (settings.scim_group_organization_id or settings.scim_default_organization_id).strip()
    if not org_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SCIM group provisioning requires SCIM_GROUP_ORGANIZATION_ID or SCIM_DEFAULT_ORGANIZATION_ID.",
        )
    if db.get(Organization, org_id) is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Configured SCIM group organization does not exist.")
    return org_id


def _group_owner(db: Session) -> User:
    settings = get_settings()
    email = (settings.scim_group_owner_email or "").strip().lower()
    if email:
        owner = db.scalar(select(User).where(func.lower(User.email) == email))
        if owner is None or not owner.active or owner.role != "admin":
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "SCIM_GROUP_OWNER_EMAIL must identify an active administrator.",
            )
        return owner
    owner = db.scalar(
        select(User).where(User.active.is_(True), User.role == "admin").order_by(User.id)
    )
    if owner is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SCIM group provisioning requires an active administrator.",
        )
    return owner


def _group_name_conflict(db: Session, display_name: str, *, exclude_id: str | None = None) -> bool:
    stmt = select(ScimGroup).where(func.lower(ScimGroup.display_name) == display_name.lower())
    if exclude_id:
        stmt = stmt.where(ScimGroup.id != exclude_id)
    return db.scalar(stmt) is not None


def _workspace_name_conflict(
    db: Session, organization_id: str, display_name: str, *, exclude_id: str | None = None
) -> bool:
    stmt = select(Workspace).where(
        Workspace.organization_id == organization_id,
        func.lower(Workspace.name) == display_name.lower(),
    )
    if exclude_id:
        stmt = stmt.where(Workspace.id != exclude_id)
    return db.scalar(stmt) is not None


def _create_group_workspace(db: Session, organization_id: str, owner: User, display_name: str) -> Workspace:
    workspace_id = f"ws_{uuid.uuid4().hex[:12]}"
    workspace = Workspace(
        id=workspace_id,
        name=display_name,
        organization_id=organization_id,
        creator_id=owner.id,
        is_private=True,
    )
    db.add(workspace)
    db.add(WorkspaceMember(
        workspace_id=workspace_id,
        user_id=owner.id,
        role="admin",
        permission="admin",
    ))
    return workspace


def _workspace_for_group(db: Session, group: ScimGroup) -> Workspace:
    workspace = db.get(Workspace, group.workspace_id)
    if workspace is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The workspace backing this SCIM group no longer exists.",
        )
    return workspace


def _other_org_grant(db: Session, group: ScimGroup, user_id: int) -> bool:
    workspace = _workspace_for_group(db, group)
    other = db.execute(
        select(ScimGroupAccess.id)
        .join(ScimGroup, ScimGroup.id == ScimGroupAccess.group_id)
        .join(Workspace, Workspace.id == ScimGroup.workspace_id)
        .where(
            ScimGroupAccess.user_id == user_id,
            ScimGroup.id != group.id,
            ScimGroup.active.is_(True),
            ScimGroup.organization_role.is_not(None),
            Workspace.organization_id == workspace.organization_id,
        )
    ).first()
    return other is not None


def _sync_org_membership(
    db: Session,
    group: ScimGroup,
    user_id: int,
    access: ScimGroupAccess,
) -> None:
    workspace = _workspace_for_group(db, group)
    organization = db.get(Organization, workspace.organization_id)
    if organization is None:
        return
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == user_id,
        )
    )
    if group.organization_role:
        if member is None:
            db.add(OrganizationMember(
                organization_id=organization.id,
                user_id=user_id,
                role=group.organization_role,
                permission=group.organization_permission or "view",
            ))
            access.created_organization_membership = True
        elif access.created_organization_membership:
            member.role = group.organization_role
            member.permission = group.organization_permission or "view"
    elif access.created_organization_membership:
        if (
            member is not None
            and organization.founder_id != user_id
            and not _other_org_grant(db, group, user_id)
        ):
            db.delete(member)
        access.created_organization_membership = False


def _sync_workspace_membership(
    db: Session,
    group: ScimGroup,
    user_id: int,
    access: ScimGroupAccess,
) -> None:
    workspace = _workspace_for_group(db, group)
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if member is None:
        db.add(WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user_id,
            role="member",
            permission="edit",
        ))
        access.created_workspace_membership = True
    # If the membership already existed, keep the existing provenance flag:
    # a row created by SCIM remains SCIM-managed on later resyncs, while a
    # new access row defaults to false and preserves manual memberships.


def _remove_access(db: Session, group: ScimGroup, access: ScimGroupAccess) -> None:
    workspace = _workspace_for_group(db, group)
    if access.created_workspace_membership:
        member = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == access.user_id,
            )
        )
        if member is not None and workspace.creator_id != access.user_id:
            db.delete(member)
            user = db.get(User, access.user_id)
            if user is not None and user.workspace_id == workspace.id:
                user.workspace_id = None
    if access.created_organization_membership:
        organization = db.get(Organization, workspace.organization_id)
        member = db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == workspace.organization_id,
                OrganizationMember.user_id == access.user_id,
            )
        )
        if (
            member is not None
            and organization is not None
            and organization.founder_id != access.user_id
            and not _other_org_grant(db, group, access.user_id)
        ):
            db.delete(member)
    db.delete(access)


def _effective_user_ids(
    db: Session, group: ScimGroup, visited: frozenset[str] = frozenset()
) -> set[int]:
    if group.id in visited:
        raise ValueError("Nested SCIM group cycle detected.")
    members = db.execute(
        select(ScimGroupMember).where(ScimGroupMember.group_id == group.id)
    ).scalars().all()
    users: set[int] = {m.user_id for m in members if m.user_id is not None}
    for member in members:
        if not member.member_group_id:
            continue
        child = db.get(ScimGroup, member.member_group_id)
        if child is not None and child.active:
            users.update(_effective_user_ids(db, child, visited | {group.id}))
    return users


def _sync_group_access(db: Session, group: ScimGroup, desired_user_ids: set[int]) -> None:
    existing = {
        access.user_id: access
        for access in db.execute(
            select(ScimGroupAccess).where(ScimGroupAccess.group_id == group.id)
        ).scalars().all()
    }
    for user_id, access in existing.items():
        if user_id not in desired_user_ids:
            _remove_access(db, group, access)
    for user_id in desired_user_ids:
        access = existing.get(user_id)
        if access is None:
            access = ScimGroupAccess(group_id=group.id, user_id=user_id)
            db.add(access)
        _sync_workspace_membership(db, group, user_id, access)
        _sync_org_membership(db, group, user_id, access)


def _replace_direct_members(
    db: Session,
    group: ScimGroup,
    user_ids: set[int],
    child_group_ids: set[str],
) -> None:
    existing = db.execute(
        select(ScimGroupMember).where(ScimGroupMember.group_id == group.id)
    ).scalars().all()
    desired = {("u", uid) for uid in user_ids} | {("g", gid) for gid in child_group_ids}
    existing_keys: set[tuple[str, Any]] = set()
    for row in existing:
        key = ("u", row.user_id) if row.user_id is not None else ("g", row.member_group_id)
        existing_keys.add(key)
        if key not in desired:
            db.delete(row)
    for kind, value in desired - existing_keys:
        if kind == "u":
            db.add(ScimGroupMember(group_id=group.id, user_id=value))
        else:
            db.add(ScimGroupMember(group_id=group.id, member_group_id=value))
    # Effective-member resolution reads ScimGroupMember rows; flush the
    # direct membership changes before resynchronizing access.
    db.flush()


def _resync_all_groups(db: Session) -> None:
    groups = db.execute(
        select(ScimGroup).where(ScimGroup.active.is_(True)).order_by(ScimGroup.id)
    ).scalars().all()
    for group in groups:
        _sync_group_access(db, group, _effective_user_ids(db, group))


def _group_member_refs(db: Session, group: ScimGroup) -> tuple[set[int], set[str]]:
    rows = db.execute(
        select(ScimGroupMember).where(ScimGroupMember.group_id == group.id)
    ).scalars().all()
    return (
        {row.user_id for row in rows if row.user_id is not None},
        {row.member_group_id for row in rows if row.member_group_id is not None},
    )


def _group_members(
    db: Session, group: ScimGroup, request: Request
) -> list[dict[str, str]]:
    users = db.execute(
        select(User)
        .join(ScimGroupMember, ScimGroupMember.user_id == User.id)
        .where(ScimGroupMember.group_id == group.id)
        .order_by(User.id)
    ).scalars().all()
    children = db.execute(
        select(ScimGroup)
        .join(ScimGroupMember, ScimGroupMember.member_group_id == ScimGroup.id)
        .where(ScimGroupMember.group_id == group.id)
        .order_by(ScimGroup.id)
    ).scalars().all()
    return [
        {
            "value": str(user.id),
            "display": user.email,
            "$ref": f"{_base_url(request)}/scim/v2/Users/{user.id}",
        }
        for user in users
    ] + [
        {
            "value": child.id,
            "display": child.display_name,
            "type": "Group",
            "$ref": f"{_base_url(request)}/scim/v2/Groups/{child.id}",
        }
        for child in children
    ]


def _group_resource(db: Session, group: ScimGroup, request: Request) -> dict[str, Any]:
    created = group.created_at.isoformat() if group.created_at else None
    updated = group.updated_at.isoformat() if group.updated_at else created
    schemas = [_GROUP_SCHEMA]
    extension: dict[str, Any] = {}
    if group.organization_role:
        schemas.append(_GROUP_EXTENSION)
        extension["organizationRole"] = group.organization_role
        extension["organizationPermission"] = group.organization_permission or "view"
    resource: dict[str, Any] = {
        "schemas": schemas,
        "id": group.id,
        "displayName": group.display_name,
        "members": _group_members(db, group, request),
        "meta": {
            **_resource_meta(request, "Groups", group.id),
            "created": created,
            "lastModified": updated,
        },
    }
    if group.external_id:
        resource["externalId"] = group.external_id
    if extension:
        resource[_GROUP_EXTENSION] = extension
    return resource


def _filtered_groups(db: Session, filter_value: str | None) -> list[ScimGroup]:
    stmt = select(ScimGroup).where(ScimGroup.active.is_(True))
    if filter_value:
        match = _GROUP_FILTER_RE.match(filter_value)
        if not match:
            raise ValueError("Unsupported SCIM group filter. Supported: displayName, externalId, id.")
        field, quoted, bare = match.groups()
        value = (quoted if quoted is not None else bare).strip()
        field = field.lower()
        if field == "id":
            group = _get_group(db, value)
            return [group] if group else []
        if field == "displayname":
            stmt = stmt.where(func.lower(ScimGroup.display_name) == value.lower())
        elif field == "externalid":
            stmt = stmt.where(func.lower(ScimGroup.external_id) == value.lower())
    return list(db.execute(stmt.order_by(ScimGroup.id)).scalars().all())


def _commit_group(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A SCIM group or workspace with that displayName already exists.",
        ) from exc


def _group_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return _scim_error(exc.status_code, str(exc.detail))
    return _scim_error(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/Groups")
def list_groups(
    request: Request,
    filter: str | None = Query(default=None),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0, le=_MAX_RESULTS),
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        groups = _filtered_groups(db, filter)
    except ValueError as exc:
        return _scim_error(400, str(exc))
    total = len(groups)
    page = groups[startIndex - 1:startIndex - 1 + count] if count else []
    return _scim_json({
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(page),
        "Resources": [_group_resource(db, group, request) for group in page],
    })


@router.post("/Groups", status_code=status.HTTP_201_CREATED)
def create_group(
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    try:
        display_name = _display_name(body)
        external_id = _external_id(body)
        organization_role, organization_permission = _organization_attributes(body)
        organization_id = _group_organization(db)
        owner = _group_owner(db)
        if _group_name_conflict(db, display_name):
            return _scim_error(409, "A SCIM group with that displayName already exists.")
        if _workspace_name_conflict(db, organization_id, display_name):
            return _scim_error(409, "A workspace with that name already exists in the group organization.")
        workspace = _create_group_workspace(db, organization_id, owner, display_name)
        group = ScimGroup(
            id=f"grp_{uuid.uuid4().hex[:16]}",
            display_name=display_name,
            external_id=external_id,
            workspace_id=workspace.id,
            organization_role=organization_role,
            organization_permission=organization_permission,
            active=True,
        )
        db.add(group)
        db.flush()
        user_ids, child_group_ids = _member_refs(
            db, body.get("members"), parent_group_id=group.id,
        )
        _replace_direct_members(db, group, user_ids, child_group_ids)
        _resync_all_groups(db)
        _commit_group(db)
        db.refresh(group)
        log_event(db, SCIM_GROUP_CREATE, target_type="scim_group", target_id=group.id,
                  detail={"workspace_id": workspace.id, "organization_id": organization_id})
        resource = _group_resource(db, group, request)
        return _scim_json(
            resource,
            status.HTTP_201_CREATED,
            headers={"Location": resource["meta"]["location"]},
        )
    except (HTTPException, ValueError) as exc:
        db.rollback()
        return _group_error(exc)


@router.get("/Groups/{group_id}")
def get_group(
    group_id: str,
    request: Request,
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    group = _get_group(db, group_id)
    if group is None:
        return _scim_error(404, "Group not found.")
    return _scim_json(_group_resource(db, group, request))


@router.put("/Groups/{group_id}")
def replace_group(
    group_id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    group = _get_group(db, group_id)
    if group is None:
        return _scim_error(404, "Group not found.")
    try:
        display_name = _display_name(body)
        organization_role, organization_permission = _organization_attributes(body)
        workspace = _workspace_for_group(db, group)
        if _group_name_conflict(db, display_name, exclude_id=group.id):
            return _scim_error(409, "A SCIM group with that displayName already exists.")
        if _workspace_name_conflict(
            db, workspace.organization_id, display_name, exclude_id=workspace.id,
        ):
            return _scim_error(409, "A workspace with that name already exists in the group organization.")
        group.display_name = display_name
        group.external_id = _external_id(body)
        group.organization_role = organization_role
        group.organization_permission = organization_permission
        workspace.name = display_name
        user_ids, child_group_ids = _member_refs(
            db, body.get("members"), parent_group_id=group.id,
        )
        _replace_direct_members(db, group, user_ids, child_group_ids)
        _resync_all_groups(db)
        _commit_group(db)
        db.refresh(group)
        log_event(db, SCIM_GROUP_UPDATE, target_type="scim_group", target_id=group.id,
                  detail={"replaced": True})
        return _scim_json(_group_resource(db, group, request))
    except (HTTPException, ValueError) as exc:
        db.rollback()
        return _group_error(exc)


@router.patch("/Groups/{group_id}")
def patch_group(
    group_id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> JSONResponse:
    group = _get_group(db, group_id)
    if group is None:
        return _scim_error(404, "Group not found.")
    operations = body.get("Operations") or body.get("operations")
    if not isinstance(operations, list) or not operations:
        return _scim_error(400, "A non-empty Operations array is required.")
    display_name = group.display_name
    external_id = group.external_id
    organization_role = group.organization_role
    organization_permission = group.organization_permission
    member_ids, child_group_ids = _group_member_refs(db, group)
    try:
        for operation in operations:
            if not isinstance(operation, dict):
                return _scim_error(400, "Each PatchOp operation must be an object.")
            op = str(operation.get("op") or "").lower()
            path = str(operation.get("path") or "").strip()
            value = operation.get("value")
            if op not in ("add", "replace", "remove"):
                return _scim_error(400, f"Unsupported PatchOp operation '{op}'.")
            if path == "displayName":
                if op == "remove":
                    return _scim_error(400, "displayName cannot be removed.")
                if not isinstance(value, str) or not value.strip():
                    return _scim_error(400, "displayName must be a non-empty string.")
                display_name = value.strip()
            elif path == "externalId":
                external_id = None if op == "remove" else _external_id({"externalId": value})
            elif path == _GROUP_EXTENSION:
                if op == "remove":
                    organization_role = None
                    organization_permission = None
                else:
                    organization_role, organization_permission = _organization_attributes({
                        _GROUP_EXTENSION: value,
                    })
            elif path in ("organizationRole", "organizationPermission"):
                if op == "remove":
                    if path == "organizationRole":
                        organization_role = None
                        organization_permission = None
                    else:
                        organization_permission = None
                elif path == "organizationRole":
                    role = str(value or "").strip().lower()
                    if role not in ("admin", "member"):
                        return _scim_error(400, "organizationRole must be 'admin' or 'member'.")
                    organization_role = role
                    if organization_permission is None:
                        organization_permission = "admin" if role == "admin" else "view"
                else:
                    permission = str(value or "").strip().lower()
                    if permission not in ("view", "edit", "admin"):
                        return _scim_error(400, "organizationPermission must be view, edit, or admin.")
                    organization_permission = permission
            elif path == "members" or _MEMBER_PATH_RE.match(path):
                if op == "replace" and path == "members":
                    member_ids = set()
                    child_group_ids = set()
                if op in ("add", "replace"):
                    new_users, new_children = _member_refs(
                        db, [value] if not isinstance(value, list) else value,
                        parent_group_id=group.id,
                    )
                    member_ids.update(new_users)
                    child_group_ids.update(new_children)
                else:
                    match = _MEMBER_PATH_RE.match(path)
                    if match:
                        raw_member = match.group(1)
                        try:
                            member_ids.discard(int(raw_member))
                        except ValueError:
                            child_group_ids.discard(raw_member)
                    elif value is not None:
                        new_users, new_children = _member_refs(
                            db, [value] if not isinstance(value, list) else value,
                            parent_group_id=group.id,
                        )
                        member_ids.difference_update(new_users)
                        child_group_ids.difference_update(new_children)
            elif not path and isinstance(value, dict):
                if "displayName" in value:
                    display_name = _display_name(value)
                if "externalId" in value:
                    external_id = _external_id(value)
                if _GROUP_EXTENSION in value:
                    organization_role, organization_permission = _organization_attributes(value)
                if "members" in value:
                    member_ids, child_group_ids = _member_refs(
                        db, value.get("members"), parent_group_id=group.id,
                    )
            else:
                return _scim_error(400, f"Unsupported PatchOp path '{path}'.")
        workspace = _workspace_for_group(db, group)
        if _group_name_conflict(db, display_name, exclude_id=group.id):
            return _scim_error(409, "A SCIM group with that displayName already exists.")
        if _workspace_name_conflict(
            db, workspace.organization_id, display_name, exclude_id=workspace.id,
        ):
            return _scim_error(409, "A workspace with that name already exists in the group organization.")
        group.display_name = display_name
        group.external_id = external_id
        group.organization_role = organization_role
        group.organization_permission = organization_permission
        workspace.name = display_name
        _replace_direct_members(db, group, member_ids, child_group_ids)
        _resync_all_groups(db)
        _commit_group(db)
        db.refresh(group)
        log_event(db, SCIM_GROUP_UPDATE, target_type="scim_group", target_id=group.id,
                  detail={"patched": True})
        return _scim_json(_group_resource(db, group, request))
    except (HTTPException, ValueError) as exc:
        db.rollback()
        return _group_error(exc)


@router.delete("/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: str,
    _: None = Depends(_require_scim),
    db: Session = Depends(get_db),
) -> Response:
    group = _get_group(db, group_id)
    if group is None:
        return _scim_error(404, "Group not found.")
    try:
        workspace = db.get(Workspace, group.workspace_id)
        access_rows = db.execute(
            select(ScimGroupAccess).where(ScimGroupAccess.group_id == group.id)
        ).scalars().all()
        for access in access_rows:
            _remove_access(db, group, access)
        db.query(ScimGroupMember).filter(ScimGroupMember.group_id == group.id).delete()
        suffix = f" [deleted {group.id}]"
        group.display_name = (group.display_name[:255 - len(suffix)] + suffix)
        if workspace is not None:
            workspace_suffix = f" [deleted {group.id}]"
            workspace.name = (workspace.name[:255 - len(workspace_suffix)] + workspace_suffix)
        group.active = False
        _resync_all_groups(db)
        _commit_group(db)
        log_event(db, SCIM_GROUP_DELETE, target_type="scim_group", target_id=group.id)
    except HTTPException as exc:
        db.rollback()
        return _scim_error(exc.status_code, str(exc.detail))
    except ValueError as exc:
        db.rollback()
        return _scim_error(400, str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
