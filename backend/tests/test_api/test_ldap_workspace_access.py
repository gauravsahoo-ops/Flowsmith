"""LDAP group-to-workspace mapping and provenance tests."""

from __future__ import annotations

import json

from app.config import get_settings
from app.db import get_session
from app.models import (
    IdentityGroupAccess,
    Organization,
    User,
    Workspace,
    WorkspaceMember,
)
from app.security.jwt import hash_password
from app.services.ldap_workspace_access import (
    parse_workspace_map,
    sync_ldap_workspace_access,
)


def _seed():
    db = get_session()
    try:
        user = User(
            email="ldap-workspace@example.com",
            password_hash=hash_password("Password123!"),
            role="member",
            active=True,
        )
        db.add(user)
        db.flush()
        db.add(Organization(
            id="org_ldap_ws", name="LDAP Workspace Org", founder_id=user.id,
        ))
        db.add(Workspace(
            id="ws_ldap", name="LDAP Workspace", organization_id="org_ldap_ws",
            creator_id=999999,
        ))
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _mapping(monkeypatch, value: dict):
    monkeypatch.setattr(
        get_settings(), "ldap_group_workspace_map", json.dumps(value), raising=False
    )


def test_parse_ldap_workspace_map():
    grants = parse_workspace_map(
        '{"Platform-Admins": ["ws_a", {"workspace_id": "ws_b", '
        '"role": "admin", "permission": "admin"}], "employees": "ws_c"}'
    )
    assert set(grants) == {"platform-admins", "employees"}
    assert grants["platform-admins"][0].workspace_id == "ws_a"
    assert grants["platform-admins"][1].role == "admin"
    assert grants["employees"][0].workspace_id == "ws_c"


def test_ldap_group_adds_and_removes_workspace_membership(monkeypatch):
    user = _seed()
    _mapping(monkeypatch, {
        "platform-admins": [{
            "workspace_id": "ws_ldap", "role": "admin", "permission": "admin",
        }]
    })
    db = get_session()
    try:
        sync_ldap_workspace_access(db, user, ("Platform-Admins",))
        member = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == "ws_ldap",
            WorkspaceMember.user_id == user.id,
        ).one()
        assert member.role == "admin"
        assert member.permission == "admin"
        access = db.query(IdentityGroupAccess).filter(
            IdentityGroupAccess.user_id == user.id
        ).one()
        assert access.created_workspace_membership is True

        sync_ldap_workspace_access(db, user, ())
        assert db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id
        ).count() == 0
        assert db.query(IdentityGroupAccess).filter(
            IdentityGroupAccess.user_id == user.id
        ).count() == 0
    finally:
        db.close()


def test_ldap_removal_preserves_manual_workspace_membership(monkeypatch):
    user = _seed()
    _mapping(monkeypatch, {"employees": ["ws_ldap"]})
    db = get_session()
    try:
        db.add(WorkspaceMember(
            workspace_id="ws_ldap", user_id=user.id, role="member", permission="view",
        ))
        db.commit()
        sync_ldap_workspace_access(db, user, ("employees",))
        access = db.query(IdentityGroupAccess).filter(
            IdentityGroupAccess.user_id == user.id
        ).one()
        assert access.created_workspace_membership is False

        sync_ldap_workspace_access(db, user, ())
        assert db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id
        ).count() == 1
    finally:
        db.close()


def test_ldap_multiple_groups_choose_strongest_grant_and_fall_back(monkeypatch):
    user = _seed()
    _mapping(monkeypatch, {
        "employees": [{"workspace_id": "ws_ldap", "permission": "view"}],
        "platform-admins": [{
            "workspace_id": "ws_ldap", "role": "admin", "permission": "admin",
        }],
    })
    db = get_session()
    try:
        sync_ldap_workspace_access(db, user, ("employees", "platform-admins"))
        member = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id
        ).one()
        assert member.role == "admin"
        assert member.permission == "admin"

        sync_ldap_workspace_access(db, user, ("employees",))
        member = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id
        ).one()
        assert member.permission == "view"
        assert db.query(IdentityGroupAccess).filter(
            IdentityGroupAccess.user_id == user.id
        ).count() == 1
    finally:
        db.close()


def test_ldap_workspace_map_ignores_missing_workspace(monkeypatch):
    user = _seed()
    _mapping(monkeypatch, {"employees": ["ws_missing"]})
    db = get_session()
    try:
        sync_ldap_workspace_access(db, user, ("employees",))
        assert db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id
        ).count() == 0
        assert db.query(IdentityGroupAccess).filter(
            IdentityGroupAccess.user_id == user.id
        ).count() == 0
    finally:
        db.close()
