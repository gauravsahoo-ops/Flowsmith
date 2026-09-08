"""Tests for Organization and Workspace CRUD APIs."""

import pytest
from fastapi.testclient import TestClient
from tests.test_api.conftest import register, auth_headers


class TestOrganizationAPI:
    def test_create_and_list_orgs(self, client: TestClient):
        data = register(client, email="org1@test.com")
        headers = auth_headers(data["token"])

        resp = client.post("/api/organizations", json={"name": "My Org", "description": "Test"}, headers=headers)
        assert resp.status_code == 200
        org_id = resp.json()["data"]["id"]
        assert org_id.startswith("org_")

        resp = client.get("/api/organizations", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

        resp = client.get(f"/api/organizations/{org_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "My Org"

        resp = client.patch(f"/api/organizations/{org_id}", json={"name": "Renamed Org"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "Renamed Org"

        resp = client.get(f"/api/organizations/{org_id}/members", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

        resp = client.delete(f"/api/organizations/{org_id}", headers=headers)
        assert resp.status_code == 200

    def test_duplicate_org_name(self, client: TestClient):
        data = register(client, email="org2@test.com")
        headers = auth_headers(data["token"])
        client.post("/api/organizations", json={"name": "Dup Org"}, headers=headers)
        resp = client.post("/api/organizations", json={"name": "Dup Org"}, headers=headers)
        assert resp.status_code == 409

    def test_add_remove_member(self, client: TestClient):
        data1 = register(client, email="orgadmin@test.com")
        data2 = register(client, email="orgmember@test.com")
        headers1 = auth_headers(data1["token"])
        headers2 = auth_headers(data2["token"])

        resp = client.post("/api/organizations", json={"name": "Member Org"}, headers=headers1)
        org_id = resp.json()["data"]["id"]

        user2_id = data2["user"]["id"]
        resp = client.post(f"/api/organizations/{org_id}/members", json={"user_id": user2_id, "role": "member"}, headers=headers1)
        assert resp.status_code == 200

        resp = client.get(f"/api/organizations/{org_id}", headers=headers2)
        assert resp.status_code == 200

        resp = client.delete(f"/api/organizations/{org_id}/members/{user2_id}", headers=headers1)
        assert resp.status_code == 200


class TestWorkspaceAPI:
    def test_create_and_list_workspaces(self, client: TestClient):
        data = register(client, email="ws1@test.com")
        headers = auth_headers(data["token"])

        resp = client.post("/api/organizations", json={"name": "WS Org"}, headers=headers)
        org_id = resp.json()["data"]["id"]

        resp = client.post("/api/workspaces", json={"name": "My WS", "organization_id": org_id}, headers=headers)
        assert resp.status_code == 200
        ws_id = resp.json()["data"]["id"]
        assert ws_id.startswith("ws_")

        resp = client.get("/api/workspaces", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

        resp = client.get(f"/api/workspaces/{ws_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "My WS"

        resp = client.patch(f"/api/workspaces/{ws_id}", json={"name": "Renamed WS"}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "Renamed WS"

        resp = client.delete(f"/api/workspaces/{ws_id}", headers=headers)
        assert resp.status_code == 200

    def test_duplicate_ws_name(self, client: TestClient):
        data = register(client, email="ws2@test.com")
        headers = auth_headers(data["token"])
        resp = client.post("/api/organizations", json={"name": "Dup WS Org"}, headers=headers)
        org_id = resp.json()["data"]["id"]
        client.post("/api/workspaces", json={"name": "Dup WS", "organization_id": org_id}, headers=headers)
        resp = client.post("/api/workspaces", json={"name": "Dup WS", "organization_id": org_id}, headers=headers)
        assert resp.status_code == 409
