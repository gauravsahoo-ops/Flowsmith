"""Map LDAP groups to organization memberships with provenance."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import IdentityOrganizationAccess, Organization, OrganizationMember, User

logger = logging.getLogger("ldap.org_access")

_ROLE_RANK = {"member": 1, "admin": 2}
_PERMISSION_RANK = {"view": 1, "edit": 2, "admin": 3}


@dataclass(frozen=True)
class OrganizationGrant:
    group: str
    organization_id: str
    role: str
    permission: str


def parse_org_map(raw: str | None = None) -> dict[str, list[OrganizationGrant]]:
    value = get_settings().ldap_group_org_map if raw is None else raw
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        logger.warning("LDAP_GROUP_ORG_MAP is not valid JSON; ignoring")
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, list[OrganizationGrant]] = {}
    for group, grants in parsed.items():
        entries = grants if isinstance(grants, list) else [grants]
        normalized: list[OrganizationGrant] = []
        for entry in entries:
            if isinstance(entry, str):
                entry = {"organization_id": entry}
            if not isinstance(entry, dict):
                continue
            organization_id = str(entry.get("organization_id") or "").strip()
            if not organization_id:
                continue
            role = str(entry.get("role") or "member").strip().lower()
            permission = str(entry.get("permission") or "view").strip().lower()
            if role not in _ROLE_RANK or permission not in _PERMISSION_RANK:
                logger.warning("Ignoring invalid LDAP organization grant for %r", group)
                continue
            normalized.append(OrganizationGrant(
                group=str(group).strip(),
                organization_id=organization_id,
                role=role,
                permission=permission,
            ))
        if normalized:
            result[str(group).strip().lower()] = normalized
    return result


def _best(rows: Sequence[IdentityOrganizationAccess]) -> tuple[str, str]:
    role = max(rows, key=lambda row: _ROLE_RANK.get(row.role, 0)).role
    permission = max(
        rows, key=lambda row: _PERMISSION_RANK.get(row.permission, 0)
    ).permission
    return role, permission


def _sync_organization(
    db: Session,
    user: User,
    organization_id: str,
    *,
    removed_created: bool,
) -> None:
    organization = db.get(Organization, organization_id)
    if organization is None:
        return
    rows = db.execute(
        select(IdentityOrganizationAccess).where(
            IdentityOrganizationAccess.user_id == user.id,
            IdentityOrganizationAccess.source == "ldap",
            IdentityOrganizationAccess.organization_id == organization_id,
        )
    ).scalars().all()
    member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if rows:
        if member is None:
            role, permission = _best(rows)
            member = OrganizationMember(
                organization_id=organization_id,
                user_id=user.id,
                role=role,
                permission=permission,
            )
            db.add(member)
            for row in rows:
                row.created_organization_membership = True
        elif any(row.created_organization_membership for row in rows):
            member.role, member.permission = _best(rows)
        return
    if (
        removed_created
        and member is not None
        and organization.founder_id != user.id
    ):
        db.delete(member)


def sync_ldap_organization_access(
    db: Session,
    user: User,
    groups: tuple[str, ...] | list[str],
) -> None:
    mapping = parse_org_map()
    desired: dict[tuple[str, str], OrganizationGrant] = {}
    for group in groups:
        for grant in mapping.get(group.strip().lower(), []):
            if db.get(Organization, grant.organization_id) is None:
                logger.warning(
                    "LDAP organization mapping references missing organization %s",
                    grant.organization_id,
                )
                continue
            desired[(grant.group.lower(), grant.organization_id)] = grant

    existing = db.execute(
        select(IdentityOrganizationAccess).where(
            IdentityOrganizationAccess.user_id == user.id,
            IdentityOrganizationAccess.source == "ldap",
        )
    ).scalars().all()
    existing_by_key = {
        (row.group_name.lower(), row.organization_id): row for row in existing
    }
    affected: set[str] = set()
    removed_created: set[str] = set()

    for key, row in existing_by_key.items():
        if key in desired:
            continue
        affected.add(row.organization_id)
        if row.created_organization_membership:
            removed_created.add(row.organization_id)
        db.delete(row)

    for key, grant in desired.items():
        affected.add(grant.organization_id)
        row = existing_by_key.get(key)
        if row is None:
            member_exists = db.scalar(
                select(OrganizationMember.id).where(
                    OrganizationMember.organization_id == grant.organization_id,
                    OrganizationMember.user_id == user.id,
                )
            ) is not None
            db.add(IdentityOrganizationAccess(
                user_id=user.id,
                source="ldap",
                group_name=grant.group,
                organization_id=grant.organization_id,
                role=grant.role,
                permission=grant.permission,
                created_organization_membership=not member_exists,
            ))
        else:
            row.role = grant.role
            row.permission = grant.permission

    db.flush()
    for organization_id in affected:
        _sync_organization(
            db,
            user,
            organization_id,
            removed_created=organization_id in removed_created,
        )
    db.commit()
