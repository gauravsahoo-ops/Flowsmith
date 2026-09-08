"""Tests for MCP, Billing, and Rate Limiting."""

import pytest
from fastapi.testclient import TestClient
from tests.test_api.conftest import register, auth_headers


class TestMCP:
    def test_list_tools(self, client: TestClient):
        data = register(client, email="mcp1@test.com")
        headers = auth_headers(data["token"])
        resp = client.get("/api/mcp/tools", headers=headers)
        assert resp.status_code == 200
        tools = resp.json()["data"]
        assert len(tools) >= 5
        tool_names = [t["name"] for t in tools]
        assert "list_workflows" in tool_names
        assert "trigger_workflow" in tool_names

    def test_call_list_workflows(self, client: TestClient):
        data = register(client, email="mcp2@test.com")
        headers = auth_headers(data["token"])
        resp = client.post("/api/mcp/call", json={"name": "list_workflows"}, headers=headers)
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_call_unknown_tool(self, client: TestClient):
        data = register(client, email="mcp3@test.com")
        headers = auth_headers(data["token"])
        resp = client.post("/api/mcp/call", json={"name": "nonexistent"}, headers=headers)
        assert resp.status_code == 404


class TestBilling:
    def test_list_plans(self, client: TestClient):
        data = register(client, email="bill1@test.com")
        headers = auth_headers(data["token"])
        resp = client.get("/api/billing/plans", headers=headers)
        assert resp.status_code == 200
        plans = resp.json()["data"]
        assert "free" in plans
        assert "pro" in plans

    def test_get_usage(self, client: TestClient):
        data = register(client, email="bill2@test.com")
        headers = auth_headers(data["token"])
        # Create org + workspace
        resp = client.post("/api/organizations", json={"name": "Bill Org"}, headers=headers)
        org_id = resp.json()["data"]["id"]
        resp = client.post("/api/workspaces", json={"name": "Bill WS", "organization_id": org_id}, headers=headers)
        ws_id = resp.json()["data"]["id"]

        resp = client.get(f"/api/billing/usage/{ws_id}", headers=headers)
        assert resp.status_code == 200
        assert "executions_month" in resp.json()["data"]

    def test_check_limit(self, client: TestClient):
        data = register(client, email="bill3@test.com")
        headers = auth_headers(data["token"])
        resp = client.post("/api/organizations", json={"name": "Limit Org"}, headers=headers)
        org_id = resp.json()["data"]["id"]
        resp = client.post("/api/workspaces", json={"name": "Limit WS", "organization_id": org_id}, headers=headers)
        ws_id = resp.json()["data"]["id"]

        resp = client.get(f"/api/billing/check-limit/{ws_id}?limit_type=executions", headers=headers)
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["within_limit"] is True
        assert body["plan"] == "Free"


class TestRateLimit:
    def test_health_bypasses_rate_limit(self, client: TestClient):
        """Health endpoint should not be rate limited."""
        for _ in range(10):
            resp = client.get("/api/health")
            assert resp.status_code == 200
