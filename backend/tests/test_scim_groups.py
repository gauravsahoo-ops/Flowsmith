"""SCIM 2.0 group provisioning and workspace mapping tests."""

from __future__ import annotations

_GROUP_EXTENSION = "urn:flowsmith:params:scim:schemas:extension:group:2.0:Group"


def _enable_scim_groups(monkeypatch, *, organization_id: str = "org_scim") -> dict[str, str]:
    from app.config import get_settings

    settings = get_settings()
    token = "scim-group-test-token-" + ("x" * 24)
    monkeypatch.setattr(settings, "scim_enabled", True)
    monkeypatch.setattr(settings, "scim_bearer_token", token)
    monkeypatch.setattr(settings, "scim_group_organization_id", organization_id)
    monkeypatch.setattr(settings, "scim_group_owner_email", "admin@example.com")
    return {"Authorization": f"Bearer {token}"}


def _seed_users_and_org() -> tuple[int, int, int]:
    from app.db import get_session
    from app.models import Organization, User
    from app.security.jwt import hash_password

    password_hash = hash_password("test-password")
    db = get_session()
    try:
        admin = User(
            email="admin@example.com",
            password_hash=password_hash,
            role="admin",
            active=True,
        )
        member_one = User(
            email="member1@example.com",
            password_hash=password_hash,
            role="member",
            active=True,
        )
        member_two = User(
            email="member2@example.com",
            password_hash=password_hash,
            role="member",
            active=True,
        )
        db.add_all([admin, member_one, member_two])
        db.flush()
        db.add(Organization(
            id="org_scim",
            name="SCIM Organization",
            founder_id=admin.id,
            is_public=False,
        ))
        db.commit()
        return admin.id, member_one.id, member_two.id
    finally:
        db.close()


def _group_payload(display_name: str, member_ids: list[int]) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": display_name,
        "externalId": f"idp-{display_name.lower()}",
        "members": [{"value": str(user_id)} for user_id in member_ids],
    }


def _group_rows(group_id: str):
    from app.db import get_session
    from app.models import ScimGroup, ScimGroupAccess, Workspace, WorkspaceMember

    db = get_session()
    try:
        group = db.get(ScimGroup, group_id)
        workspace = db.get(Workspace, group.workspace_id) if group else None
        members = db.query(ScimGroupAccess).filter(ScimGroupAccess.group_id == group_id).all()
        workspace_members = (
            db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace.id).all()
            if workspace else []
        )
        return group, workspace, members, workspace_members
    finally:
        db.close()


def test_scim_groups_are_discovered(client, monkeypatch):
    headers = _enable_scim_groups(monkeypatch)
    resource_types = client.get("/scim/v2/ResourceTypes", headers=headers)
    assert resource_types.status_code == 200
    ids = {item["id"] for item in resource_types.json()["Resources"]}
    assert ids == {"User", "Group"}
    schemas = client.get("/scim/v2/Schemas", headers=headers)
    assert schemas.status_code == 200
    schema_ids = {item["id"] for item in schemas.json()["Resources"]}
    assert "urn:ietf:params:scim:schemas:core:2.0:Group" in schema_ids
    assert _GROUP_EXTENSION in schema_ids


def test_scim_group_lifecycle_maps_to_workspace(client, monkeypatch):
    admin_id, member_one, member_two = _seed_users_and_org()
    headers = _enable_scim_groups(monkeypatch)

    created = client.post(
        "/scim/v2/Groups",
        headers=headers,
        json=_group_payload("Engineering", [member_one]),
    )
    assert created.status_code == 201, created.text
    assert created.headers["content-type"].startswith("application/scim+json")
    group_id = created.json()["id"]
    assert created.json()["displayName"] == "Engineering"
    assert created.json()["externalId"] == "idp-engineering"
    assert [m["value"] for m in created.json()["members"]] == [str(member_one)]
    assert "Location" in created.headers

    duplicate = client.post(
        "/scim/v2/Groups",
        headers=headers,
        json=_group_payload("Engineering", []),
    )
    assert duplicate.status_code == 409

    group, workspace, members, workspace_members = _group_rows(group_id)
    assert group is not None and group.active is True
    assert workspace is not None
    assert workspace.organization_id == "org_scim"
    assert workspace.creator_id == admin_id
    assert {member.user_id for member in members} == {member_one}
    assert members[0].created_workspace_membership is True
    assert {member.user_id for member in workspace_members} == {admin_id, member_one}
    assert next(m for m in workspace_members if m.user_id == member_one).permission == "edit"

    listed = client.get(
        '/scim/v2/Groups?filter=displayName%20eq%20%22Engineering%22',
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["totalResults"] == 1
    assert listed.json()["Resources"][0]["id"] == group_id

    user = client.get(f"/scim/v2/Users/{member_one}", headers=headers)
    assert user.status_code == 200
    assert user.json()["groups"][0]["value"] == group_id

    added = client.patch(
        f"/scim/v2/Groups/{group_id}",
        headers=headers,
        json={"Operations": [{
            "op": "add",
            "path": "members",
            "value": [{"value": str(member_two)}],
        }]},
    )
    assert added.status_code == 200
    assert {m["value"] for m in added.json()["members"]} == {str(member_one), str(member_two)}

    removed = client.patch(
        f"/scim/v2/Groups/{group_id}",
        headers=headers,
        json={"Operations": [{
            "op": "remove",
            "path": f'members[value eq "{member_one}"]',
        }]},
    )
    assert removed.status_code == 200
    assert [m["value"] for m in removed.json()["members"]] == [str(member_two)]
    _, _, _, workspace_members = _group_rows(group_id)
    assert member_one not in {member.user_id for member in workspace_members}
    assert member_two in {member.user_id for member in workspace_members}

    replaced = client.put(
        f"/scim/v2/Groups/{group_id}",
        headers=headers,
        json=_group_payload("Platform", [member_one]),
    )
    assert replaced.status_code == 200
    assert replaced.json()["displayName"] == "Platform"
    group, workspace, members, workspace_members = _group_rows(group_id)
    assert workspace is not None and workspace.name == "Platform"
    assert {member.user_id for member in members} == {member_one}
    assert member_two not in {member.user_id for member in workspace_members}

    deleted = client.delete(f"/scim/v2/Groups/{group_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/scim/v2/Groups/{group_id}", headers=headers).status_code == 404
    group, workspace, members, workspace_members = _group_rows(group_id)
    assert group is not None and group.active is False
    assert workspace is not None and "deleted" in workspace.name
    assert members == []
    assert admin_id in {member.user_id for member in workspace_members}
    assert member_one not in {member.user_id for member in workspace_members}

    recreated = client.post(
        "/scim/v2/Groups",
        headers=headers,
        json=_group_payload("Platform", []),
    )
    assert recreated.status_code == 201


def test_scim_group_removal_preserves_manual_workspace_membership(client, monkeypatch):
    _, member_one, member_two = _seed_users_and_org()
    headers = _enable_scim_groups(monkeypatch)
    created = client.post(
        "/scim/v2/Groups",
        headers=headers,
        json=_group_payload("ManualPreserve", [member_one]),
    )
    group_id = created.json()["id"]

    from app.db import get_session
    from app.models import ScimGroup, WorkspaceMember

    db = get_session()
    try:
        group = db.get(ScimGroup, group_id)
        assert group is not None
        db.add(WorkspaceMember(
            workspace_id=group.workspace_id,
            user_id=member_two,
            role="member",
            permission="view",
        ))
        db.commit()
    finally:
        db.close()

    added = client.patch(
        f"/scim/v2/Groups/{group_id}",
        headers=headers,
        json={"Operations": [{
            "op": "add",
            "path": "members",
            "value": [{"value": str(member_two)}],
        }]},
    )
    assert added.status_code == 200
    removed = client.patch(
        f"/scim/v2/Groups/{group_id}",
        headers=headers,
        json={"Operations": [{
            "op": "remove",
            "path": f'members[value eq "{member_two}"]',
        }]},
    )
    assert removed.status_code == 200

    db = get_session()
    try:
        group = db.get(ScimGroup, group_id)
        assert group is not None
        membership = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == group.workspace_id,
            WorkspaceMember.user_id == member_two,
        ).one()
        assert membership.permission == "view"
    finally:
        db.close()


def test_scim_group_can_grant_organization_role(client, monkeypatch):
    _, member_one, member_two = _seed_users_and_org()
    headers = _enable_scim_groups(monkeypatch)
    payload = _group_payload("OrgRole", [member_one])
    payload[_GROUP_EXTENSION] = {
        "organizationRole": "member",
        "organizationPermission": "view",
    }
    created = client.post("/scim/v2/Groups", headers=headers, json=payload)
    assert created.status_code == 201
    group_id = created.json()["id"]
    assert created.json()[_GROUP_EXTENSION]["organizationRole"] == "member"

    from app.db import get_session
    from app.models import OrganizationMember

    db = get_session()
    try:
        org_member = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == "org_scim",
            OrganizationMember.user_id == member_one,
        ).one()
        assert (org_member.role, org_member.permission) == ("member", "view")

        manual = OrganizationMember(
            organization_id="org_scim",
            user_id=member_two,
            role="member",
            permission="view",
        )
        db.add(manual)
        db.commit()
    finally:
        db.close()

    promoted = client.patch(
        f"/scim/v2/Groups/{group_id}",
        headers=headers,
        json={"Operations": [{
            "op": "replace",
            "path": _GROUP_EXTENSION,
            "value": {"organizationRole": "admin", "organizationPermission": "edit"},
        }]},
    )
    assert promoted.status_code == 200
    assert promoted.json()[_GROUP_EXTENSION]["organizationPermission"] == "edit"

    db = get_session()
    try:
        org_member = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == "org_scim",
            OrganizationMember.user_id == member_one,
        ).one()
        assert (org_member.role, org_member.permission) == ("admin", "edit")
    finally:
        db.close()

    removed = client.patch(
        f"/scim/v2/Groups/{group_id}",
        headers=headers,
        json={"Operations": [{
            "op": "remove",
            "path": f'members[value eq "{member_one}"]',
        }]},
    )
    assert removed.status_code == 200
    db = get_session()
    try:
        assert db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == "org_scim",
            OrganizationMember.user_id == member_one,
        ).count() == 0
        assert db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == "org_scim",
            OrganizationMember.user_id == member_two,
        ).count() == 1
    finally:
        db.close()


def test_scim_nested_group_membership_and_cycle_guard(client, monkeypatch):
    _, member_one, _ = _seed_users_and_org()
    headers = _enable_scim_groups(monkeypatch)

    child = client.post(
        "/scim/v2/Groups",
        headers=headers,
        json=_group_payload("Child Team", [member_one]),
    )
    assert child.status_code == 201
    child_id = child.json()["id"]

    parent_payload = _group_payload("Parent Team", [])
    parent_payload["members"] = [{"value": child_id, "type": "Group"}]
    parent = client.post("/scim/v2/Groups", headers=headers, json=parent_payload)
    assert parent.status_code == 201
    parent_id = parent.json()["id"]
    assert parent.json()["members"][0]["type"] == "Group"
    assert parent.json()["members"][0]["value"] == child_id

    from app.db import get_session
    from app.models import ScimGroup, WorkspaceMember

    db = get_session()
    try:
        parent_group = db.get(ScimGroup, parent_id)
        assert parent_group is not None
        assert member_one in {
            m.user_id for m in db.query(WorkspaceMember).filter(
                WorkspaceMember.workspace_id == parent_group.workspace_id
            ).all()
        }
    finally:
        db.close()

    user = client.get(f"/scim/v2/Users/{member_one}", headers=headers)
    assert user.status_code == 200
    group_ids = {g["value"] for g in user.json()["groups"]}
    assert {child_id, parent_id}.issubset(group_ids)

    removed = client.patch(
        f"/scim/v2/Groups/{child_id}",
        headers=headers,
        json={"Operations": [{
            "op": "remove",
            "path": f'members[value eq "{member_one}"]',
        }]},
    )
    assert removed.status_code == 200
    db = get_session()
    try:
        parent_group = db.get(ScimGroup, parent_id)
        assert parent_group is not None
        assert member_one not in {
            m.user_id for m in db.query(WorkspaceMember).filter(
                WorkspaceMember.workspace_id == parent_group.workspace_id
            ).all()
        }
    finally:
        db.close()

    cycle = client.patch(
        f"/scim/v2/Groups/{child_id}",
        headers=headers,
        json={"Operations": [{
            "op": "add",
            "path": "members",
            "value": [{"value": parent_id, "type": "Group"}],
        }]},
    )
    assert cycle.status_code == 400
    assert "cycle" in cycle.text.lower()


def test_scim_group_requires_configured_organization(client, monkeypatch):
    _seed_users_and_org()
    headers = _enable_scim_groups(monkeypatch, organization_id="")
    response = client.post(
        "/scim/v2/Groups",
        headers=headers,
        json=_group_payload("NoOrg", []),
    )
    assert response.status_code == 503


def test_scim_group_rejects_unknown_member(client, monkeypatch):
    _seed_users_and_org()
    headers = _enable_scim_groups(monkeypatch)
    response = client.post(
        "/scim/v2/Groups",
        headers=headers,
        json=_group_payload("BadMember", [999999]),
    )
    assert response.status_code == 400
