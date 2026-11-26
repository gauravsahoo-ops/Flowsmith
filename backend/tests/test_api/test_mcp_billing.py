"""Tests for MCP and Rate Limiting."""

import gzip
import json

from fastapi.testclient import TestClient
from tests.test_api.conftest import auth_headers, make_workflow, register


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

    def test_account_exports_are_private(
        self, client: TestClient, tmp_path, monkeypatch
    ):
        from app.services import user_export

        monkeypatch.setattr(user_export, "_ROOT", tmp_path / "users")

        first = register(client, email="mcp-export-first@test.com")
        second = register(client, email="mcp-export-second@test.com")
        first_headers = auth_headers(first["token"])
        second_headers = auth_headers(second["token"])

        wf = make_workflow("wf_export_private", "Private Export Workflow")
        created = client.post("/api/workflows", json=wf, headers=first_headers)
        assert created.status_code == 201, created.text

        created_export = client.post(
            "/api/mcp/call",
            json={"name": "create_backup", "arguments": {"name": "my_export"}},
            headers=first_headers,
        )
        assert created_export.status_code == 200, created_export.text
        filename = created_export.json()["data"]["filename"]
        assert filename == "my_export.json.gz"

        first_list = client.post(
            "/api/mcp/call", json={"name": "list_backups"}, headers=first_headers
        ).json()["data"]
        assert [item["filename"] for item in first_list] == [filename]
        second_list = client.post(
            "/api/mcp/call", json={"name": "list_backups"}, headers=second_headers
        ).json()["data"]
        assert second_list == []

        path = user_export.user_export_dir(first["user"]["id"]) / filename
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        assert payload["user"]["id"] == first["user"]["id"]
        assert [row["id"] for row in payload["workflows"]] == ["wf_export_private"]
        assert all("password" not in json.dumps(row) for row in payload["credentials"])


class TestRateLimit:
    def test_health_bypasses_rate_limit(self, client: TestClient):
        """Health endpoint should not be rate limited."""
        for _ in range(10):
            resp = client.get("/api/health")
            assert resp.status_code == 200
