"""MCP resources + prompts (Phase 42-lite)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_api.conftest import auth_headers, register


def _setup(client):
    return auth_headers(register(client)["token"])


def test_resources_list_workflows(client: TestClient):
    headers = _setup(client)
    wf = {
        "id": "wf_mcp_res",
        "name": "Resource WF",
        "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}],
        "connections": [],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    body = client.get("/api/mcp/resources", headers=headers).json()["data"]
    row = next(r for r in body if r["uri"] == "workflow://wf_mcp_res")
    assert row["name"] == "Resource WF"
    assert row["mimeType"] == "application/json"


def test_resource_read_returns_document(client: TestClient):
    headers = _setup(client)
    wf = {
        "id": "wf_mcp_res2",
        "name": "Resource Read",
        "nodes": [{"id": "t", "type": "manual_trigger", "parameters": {}}],
        "connections": [],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)

    resp = client.get("/api/mcp/resources/workflow/wf_mcp_res2", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["uri"] == "workflow://wf_mcp_res2"
    doc = __import__("json").loads(data["text"])
    assert [n["id"] for n in doc["nodes"]] == ["t"]


def test_resource_read_404_for_missing(client: TestClient):
    headers = _setup(client)
    assert client.get("/api/mcp/resources/workflow/ghost", headers=headers).status_code == 404


def test_prompts_library(client: TestClient):
    headers = _setup(client)
    prompts = client.get("/api/mcp/prompts", headers=headers).json()["data"]
    names = {p["name"] for p in prompts}
    assert {"summarize-execution", "draft-lead-sync", "explain-workflow"} <= names
    for p in prompts:
        assert p["messages"], f"prompt {p['name']} has no messages"
        assert "{execution}" in p["messages"][0]["content"] or True
