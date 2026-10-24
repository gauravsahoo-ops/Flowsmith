"""SCIM 2.0 user provisioning tests."""

from __future__ import annotations


def _enable_scim(monkeypatch) -> dict[str, str]:
    from app.config import get_settings

    settings = get_settings()
    token = "scim-test-token-" + ("x" * 24)
    monkeypatch.setattr(settings, "scim_enabled", True)
    monkeypatch.setattr(settings, "scim_bearer_token", token)
    return {"Authorization": f"Bearer {token}"}


def _user_payload(email: str = "ada@example.com", active: bool = True) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": email,
        "name": {"givenName": "Ada", "familyName": "Lovelace"},
        "emails": [{"value": email, "primary": True}],
        "active": active,
        "roles": [{"value": "member"}],
    }


def test_scim_disabled_hides_endpoint(client):
    resp = client.get("/scim/v2/ServiceProviderConfig")
    assert resp.status_code == 404


def test_scim_requires_valid_bearer_token(client, monkeypatch):
    headers = _enable_scim(monkeypatch)
    assert client.get("/scim/v2/ServiceProviderConfig").status_code == 401
    assert client.get(
        "/scim/v2/ServiceProviderConfig",
        headers={"Authorization": "Bearer wrong-token"},
    ).status_code == 401
    assert client.get("/scim/v2/ServiceProviderConfig", headers=headers).status_code == 200


def test_scim_user_lifecycle(client, monkeypatch):
    headers = _enable_scim(monkeypatch)
    created = client.post("/scim/v2/Users", headers=headers, json=_user_payload())
    assert created.status_code == 201
    assert created.headers["content-type"].startswith("application/scim+json")
    resource = created.json()
    user_id = resource["id"]
    assert resource["userName"] == "ada@example.com"
    assert resource["active"] is True
    assert resource["roles"][0]["value"] == "member"
    assert "Location" in created.headers

    duplicate = client.post("/scim/v2/Users", headers=headers, json=_user_payload())
    assert duplicate.status_code == 409

    listed = client.get(
        '/scim/v2/Users?filter=userName%20eq%20%22ada%40example.com%22',
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["totalResults"] == 1
    assert listed.json()["Resources"][0]["id"] == user_id

    fetched = client.get(f"/scim/v2/Users/{user_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["emails"][0]["value"] == "ada@example.com"

    patched = client.patch(
        f"/scim/v2/Users/{user_id}",
        headers=headers,
        json={"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
              "Operations": [{"op": "replace", "path": "active", "value": False}]},
    )
    assert patched.status_code == 200
    assert patched.json()["active"] is False

    deleted = client.delete(f"/scim/v2/Users/{user_id}", headers=headers)
    assert deleted.status_code == 204
    still_there = client.get(f"/scim/v2/Users/{user_id}", headers=headers)
    assert still_there.status_code == 200
    assert still_there.json()["active"] is False


def test_scim_put_and_role_patch(client, monkeypatch):
    headers = _enable_scim(monkeypatch)
    created = client.post("/scim/v2/Users", headers=headers, json=_user_payload("grace@example.com"))
    user_id = created.json()["id"]

    replaced = client.put(
        f"/scim/v2/Users/{user_id}",
        headers=headers,
        json={**_user_payload("grace@example.com"), "roles": [{"value": "admin"}]},
    )
    assert replaced.status_code == 200
    assert replaced.json()["roles"][0]["value"] == "admin"

    patched = client.patch(
        f"/scim/v2/Users/{user_id}",
        headers=headers,
        json={"Operations": [{"op": "replace", "path": "roles", "value": [{"value": "member"}]}]},
    )
    assert patched.status_code == 200
    assert patched.json()["roles"][0]["value"] == "member"


def test_scim_default_scope_assigns_org_and_workspace(client, monkeypatch):
    from app.config import get_settings
    from app.db import get_session
    from app.models import Organization, OrganizationMember, User, Workspace, WorkspaceMember

    db = get_session()
    try:
        db.add(Organization(id="org_scim", name="SCIM Org", founder_id=1, is_public=False))
        db.add(Workspace(
            id="ws_scim", name="SCIM Workspace", organization_id="org_scim",
            creator_id=1, is_private=True,
        ))
        db.commit()
    finally:
        db.close()

    headers = _enable_scim(monkeypatch)
    settings = get_settings()
    monkeypatch.setattr(settings, "scim_default_organization_id", "org_scim")
    monkeypatch.setattr(settings, "scim_default_workspace_id", "ws_scim")
    created = client.post("/scim/v2/Users", headers=headers, json=_user_payload("scoped@example.com"))
    assert created.status_code == 201

    db = get_session()
    try:
        user = db.query(User).filter(User.email == "scoped@example.com").one()
        assert user.organization_id == "org_scim"
        assert user.workspace_id == "ws_scim"
        assert db.query(OrganizationMember).filter(OrganizationMember.user_id == user.id).count() == 1
        assert db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).count() == 1
    finally:
        db.close()


def test_scim_rejects_invalid_filter(client, monkeypatch):
    headers = _enable_scim(monkeypatch)
    resp = client.get("/scim/v2/Users?filter=displayName%20co%20Ada", headers=headers)
    assert resp.status_code == 400
    assert resp.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
