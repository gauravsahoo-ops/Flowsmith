"""Map LDAP groups to workspace memberships.

The mapping is optional and additive to the normal organization/workspace
default scope. Memberships created here are tracked separately so removing an
LDAP group does not revoke a manually granted workspace membership.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IdentityGroupAccess, User, Workspace, WorkspaceMember

logger = logging.getLogger("ldap.access")

_ROLE_RANK = {"member": 1, "admin": 2}
_PERMISSION_RANK = {"view": 1, "edit": 2, "admin": 3}


@dataclass(frozen=True)
class WorkspaceGrant:
    group: str
    workspace_id: str
    role: str
    permission: str


def parse_workspace_map(raw: str | None = None) -> dict[str, list[WorkspaceGrant]]:
    value = get_settings().ldap_group_workspace_map if raw is None else raw
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        logger.warning("LDAP_GROUP_WORKSPACE_MAP is not valid JSON; ignoring")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("LDAP_GROUP_WORKSPACE_MAP must be a JSON object; ignoring")
        return {}
    result: dict[str, list[WorkspaceGrant]] = {}
    for group, grants in parsed.items():
        entries = grants if isinstance(grants, list) else [grants]
        normalized: list[WorkspaceGrant] = []
        for entry in entries:
            if isinstance(entry, str):
                entry = {"workspace_id": entry}
            if not isinstance(entry, dict):
                continue
            workspace_id = str(entry.get("workspace_id") or "").strip()
            if not workspace_id:
                continue
            role = str(entry.get("role") or "member").strip().lower()
            permission = str(entry.get("permission") or "edit").strip().lower()
            if role not in _ROLE_RANK or permission not in _PERMISSION_RANK:
                logger.warning("Ignoring invalid LDAP workspace grant for group %r", group)
                continue
            normalized.append(WorkspaceGrant(
                group=str(group).strip(),
                workspace_id=workspace_id,
                role=role,
                permission=permission,
            ))
        if normalized:
            result[str(group).strip().lower()] = normalized
    return result


def _best(rows: Sequence[IdentityGroupAccess]) -> tuple[str, str]:
    role = max(rows, key=lambda row: _ROLE_RANK.get(row.role, 0)).role
    permission = max(
        rows, key=lambda row: _PERMISSION_RANK.get(row.permission, 0)
    ).permission
    return role, permission


def _sync_workspace(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    removed_created: bool,
) -> None:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return
    rows = db.execute(
        select(IdentityGroupAccess).where(
            IdentityGroupAccess.user_id == user.id,
            IdentityGroupAccess.source == "ldap",
            IdentityGroupAccess.workspace_id == workspace_id,
        )
    ).scalars().all()
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if rows:
        if member is None:
            role, permission = _best(rows)
            member = WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user.id,
                role=role,
                permission=permission,
            )
            db.add(member)
            for row in rows:
                row.created_workspace_membership = True
        elif any(row.created_workspace_membership for row in rows):
            member.role, member.permission = _best(rows)
        return
    if (
        removed_created
        and member is not None
        and workspace.creator_id != user.id
    ):
        db.delete(member)
        if user.workspace_id == workspace_id:
            user.workspace_id = None


def sync_ldap_workspace_access(
    db: Session,
    user: User,
    groups: tuple[str, ...] | list[str],
) -> None:
    """Materialize configured LDAP group -> workspace grants for one login."""
    mapping = parse_workspace_map()
    desired: dict[tuple[str, str], WorkspaceGrant] = {}
    for group in groups:
        for grant in mapping.get(group.strip().lower(), []):
            if db.get(Workspace, grant.workspace_id) is None:
                logger.warning(
                    "LDAP workspace mapping references missing workspace %s",
                    grant.workspace_id,
                )
                continue
            desired[(grant.group.lower(), grant.workspace_id)] = grant

    existing = db.execute(
        select(IdentityGroupAccess).where(
            IdentityGroupAccess.user_id == user.id,
            IdentityGroupAccess.source == "ldap",
        )
    ).scalars().all()
    existing_by_key = {
        (row.group_name.lower(), row.workspace_id): row for row in existing
    }
    affected: set[str] = set()
    removed_created: set[str] = set()

    for key, row in existing_by_key.items():
        if key in desired:
            continue
        affected.add(row.workspace_id)
        if row.created_workspace_membership:
            removed_created.add(row.workspace_id)
        db.delete(row)

    for key, grant in desired.items():
        affected.add(grant.workspace_id)
        row = existing_by_key.get(key)
        member_exists = db.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == grant.workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        ) is not None
        if row is None:
            db.add(IdentityGroupAccess(
                user_id=user.id,
                source="ldap",
                group_name=grant.group,
                workspace_id=grant.workspace_id,
                role=grant.role,
                permission=grant.permission,
                created_workspace_membership=not member_exists,
            ))
        else:
            row.role = grant.role
            row.permission = grant.permission

    db.flush()
    for workspace_id in affected:
        _sync_workspace(
            db,
            user,
            workspace_id,
            removed_created=workspace_id in removed_created,
        )
    db.commit()
