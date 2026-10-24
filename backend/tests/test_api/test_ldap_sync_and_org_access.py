"""LDAP organization-access mapping and background synchronization tests."""

from __future__ import annotations

import json

from app.config import get_settings
from app.db import get_session
from app.models import (
    IdentityOrganizationAccess,
    Organization,
    OrganizationMember,
    User,
    Workspace,
)
from app.security.jwt import hash_password
from app.services.ldap_auth import LdapProfile
from app.services import ldap_sync as ldap_sync_module
from app.services.ldap_org_access import (
    parse_org_map,
    sync_ldap_organization_access,
)


def _seed_user(email: str = "ldap-sync@example.com"):
    db = get_session()
    try:
        user = User(
            email=email,
            password_hash=hash_password("Password123!"),
            role="member",
            active=True,
            ldap_dn="uid=ldap-sync,ou=people,dc=example,dc=org",
            ldap_groups=json.dumps(["employees"]),
        )
        db.add(user)
        db.flush()
        db.add(Organization(
            id="org_ldap_sync", name="LDAP Sync Org", founder_id=999998,
        ))
        db.add(Workspace(
            id="ws_ldap_sync", name="LDAP Sync Workspace",
            organization_id="org_ldap_sync", creator_id=999999,
        ))
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def test_parse_and_sync_ldap_organization_access(monkeypatch):
    user = _seed_user()
    monkeypatch.setattr(
        get_settings(),
        "ldap_group_org_map",
        json.dumps({
            "platform-admins": [{
                "organization_id": "org_ldap_sync",
                "role": "admin",
                "permission": "admin",
            }]
        }),
        raising=False,
    )
    grants = parse_org_map()
    assert grants["platform-admins"][0].organization_id == "org_ldap_sync"

    db = get_session()
    try:
        sync_ldap_organization_access(db, user, ("Platform-Admins",))
        member = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == "org_ldap_sync",
            OrganizationMember.user_id == user.id,
        ).one()
        assert member.role == "admin"
        assert member.permission == "admin"
        access = db.query(IdentityOrganizationAccess).filter(
            IdentityOrganizationAccess.user_id == user.id
        ).one()
        assert access.created_organization_membership is True

        sync_ldap_organization_access(db, user, ())
        assert db.query(OrganizationMember).filter(
            OrganizationMember.user_id == user.id
        ).count() == 0
    finally:
        db.close()


def test_manual_org_membership_is_preserved(monkeypatch):
    user = _seed_user("ldap-manual-org@example.com")
    monkeypatch.setattr(
        get_settings(),
        "ldap_group_org_map",
        '{"employees":["org_ldap_sync"]}',
        raising=False,
    )
    db = get_session()
    try:
        db.add(OrganizationMember(
            organization_id="org_ldap_sync",
            user_id=user.id,
            role="member",
            permission="view",
        ))
        db.commit()
        sync_ldap_organization_access(db, user, ("employees",))
        access = db.query(IdentityOrganizationAccess).filter(
            IdentityOrganizationAccess.user_id == user.id
        ).one()
        assert access.created_organization_membership is False
        sync_ldap_organization_access(db, user, ())
        assert db.query(OrganizationMember).filter(
            OrganizationMember.user_id == user.id
        ).count() == 1
    finally:
        db.close()


def test_background_sync_refreshes_groups_role_and_memberships(monkeypatch):
    user = _seed_user("ldap-background@example.com")
    settings = get_settings()
    monkeypatch.setattr(settings, "ldap_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ldap_sync_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ldap_default_role", "member", raising=False)
    monkeypatch.setattr(settings, "ldap_group_role_map", '{"platform-admins":"admin"}', raising=False)
    monkeypatch.setattr(settings, "ldap_group_workspace_map", '{"platform-admins":["ws_ldap_sync"]}', raising=False)
    monkeypatch.setattr(settings, "ldap_group_org_map", '{"platform-admins":["org_ldap_sync"]}', raising=False)
    monkeypatch.setattr(
        ldap_sync_module,
        "lookup_ldap_profile",
        lambda dn: LdapProfile(
            username="ldap-sync",
            email="ldap-background@example.com",
            dn=dn,
            display_name="LDAP Sync",
            groups=("platform-admins",),
        ),
    )

    refreshed = ldap_sync_module.sync_all_ldap_users()
    assert refreshed == 1

    db = get_session()
    try:
        current = db.get(User, user.id)
        assert current is not None
        assert current.role == "admin"
        assert current.ldap_synced_at is not None
        assert json.loads(current.ldap_groups or "[]") == ["platform-admins"]
        assert db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == "org_ldap_sync",
            OrganizationMember.user_id == user.id,
        ).count() == 1
    finally:
        db.close()


def test_background_sync_does_not_deactivate_missing_users(monkeypatch):
    user = _seed_user("ldap-missing@example.com")
    settings = get_settings()
    monkeypatch.setattr(settings, "ldap_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ldap_sync_enabled", True, raising=False)
    monkeypatch.setattr(ldap_sync_module, "lookup_ldap_profile", lambda dn: None)

    assert ldap_sync_module.sync_all_ldap_users() == 0
    db = get_session()
    try:
        current = db.get(User, user.id)
        assert current is not None
        assert current.active is True
    finally:
        db.close()
