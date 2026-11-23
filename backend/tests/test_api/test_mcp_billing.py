"""Tests for MCP and Rate Limiting."""

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


class TestRateLimit:
    def test_health_bypasses_rate_limit(self, client: TestClient):
        """Health endpoint should not be rate limited."""
        for _ in range(10):
            resp = client.get("/api/health")
            assert resp.status_code == 200
