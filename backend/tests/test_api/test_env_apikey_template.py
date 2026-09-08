"""Tests for Environment, API Key, and Template APIs."""

import pytest
from fastapi.testclient import TestClient
from tests.test_api.conftest import register, auth_headers


class TestEnvironmentAPI:
    def test_create_and_list_env(self, client: TestClient):
        data = register(client, email="env1@test.com")
        headers = auth_headers(data["token"])

        # Create org + workspace first
        resp = client.post("/api/organizations", json={"name": "Env Org"}, headers=headers)
        org_id = resp.json()["data"]["id"]
        resp = client.post("/api/workspaces", json={"name": "Env WS", "organization_id": org_id}, headers=headers)
        ws_id = resp.json()["data"]["id"]

        # Create env var
        resp = client.post("/api/environments", json={"workspace_id": ws_id, "key": "API_URL", "value": "https://api.test.com"}, headers=headers)
        assert resp.status_code == 200
        env_id = resp.json()["data"]["id"]

        # List env vars
        resp = client.get(f"/api/environments/{ws_id}", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1
        assert resp.json()["data"][0]["key"] == "API_URL"

        # Delete
        resp = client.delete(f"/api/environments/{env_id}", headers=headers)
        assert resp.status_code == 200

    def test_env_upsert(self, client: TestClient):
        """Creating same key twice should update the value."""
        data = register(client, email="env2@test.com")
        headers = auth_headers(data["token"])
        resp = client.post("/api/organizations", json={"name": "Upsert Org"}, headers=headers)
        org_id = resp.json()["data"]["id"]
        resp = client.post("/api/workspaces", json={"name": "Upsert WS", "organization_id": org_id}, headers=headers)
        ws_id = resp.json()["data"]["id"]

        client.post("/api/environments", json={"workspace_id": ws_id, "key": "K", "value": "v1"}, headers=headers)
        resp = client.post("/api/environments", json={"workspace_id": ws_id, "key": "K", "value": "v2"}, headers=headers)
        assert resp.status_code == 200

        resp = client.get(f"/api/environments/{ws_id}", headers=headers)
        assert resp.json()["data"][0]["value"] == "v2"

    def test_env_secret_masked(self, client: TestClient):
        data = register(client, email="env3@test.com")
        headers = auth_headers(data["token"])
        resp = client.post("/api/organizations", json={"name": "Sec Org"}, headers=headers)
        org_id = resp.json()["data"]["id"]
        resp = client.post("/api/workspaces", json={"name": "Sec WS", "organization_id": org_id}, headers=headers)
        ws_id = resp.json()["data"]["id"]

        client.post("/api/environments", json={"workspace_id": ws_id, "key": "SECRET", "value": "supersecret123", "is_secret": True}, headers=headers)
        resp = client.get(f"/api/environments/{ws_id}", headers=headers)
        val = resp.json()["data"][0]["value"]
        assert val.startswith("***")
        assert val != "supersecret123"


class TestAPIKeyAPI:
    def test_create_and_list_keys(self, client: TestClient):
        data = register(client, email="key1@test.com")
        headers = auth_headers(data["token"])

        resp = client.post("/api/apikeys", json={"name": "My Key"}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert "key" in body
        assert body["name"] == "My Key"
        key_id = body["id"]

        resp = client.get("/api/apikeys", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

        resp = client.delete(f"/api/apikeys/{key_id}", headers=headers)
        assert resp.status_code == 200


class TestTemplateAPI:
    def test_create_and_list_templates(self, client: TestClient):
        data = register(client, email="tmpl1@test.com")
        headers = auth_headers(data["token"])

        wf_data = {"nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}], "connections": []}
        resp = client.post("/api/templates", json={"name": "My Template", "description": "Test", "workflow_data": wf_data}, headers=headers)
        assert resp.status_code == 200
        tmpl_id = resp.json()["data"]["id"]

        resp = client.get("/api/templates", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

        resp = client.post(f"/api/templates/{tmpl_id}/use", headers=headers)
        assert resp.status_code == 200
        assert "workflow_data" in resp.json()["data"]
