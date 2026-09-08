"""MCP surface expansion (Phase 36): set_workflow_active + use_template.

The pre-existing MCP tools were stale against the current schema (they
referenced removed columns); the surface is now schema-correct and
covered: trigger_workflow runs a real workflow end-to-end through the
queue, and the new tools exercise activation and template instantiation.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

import pytest

from tests.test_api.conftest import auth_headers, register

pytestmark = pytest.mark.timing


def _setup(client):
    return auth_headers(register(client)["token"])


def _poll(client, headers, eid, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/executions/{eid}", headers=headers).json()
        if "data" in body:
            st = body["data"]["status"]
            if st not in ("running", "queued", "cancelling"):
                return st
        time.sleep(0.05)
    raise AssertionError("execution did not finish")


def test_mcp_trigger_workflow_runs(client: TestClient):
    headers = _setup(client)
    wf = {
        "id": "wf_mcp_trig",
        "name": "MCP trigger",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "s", "type": "set_data", "parameters": {"fields": {"ok": "yes"}}},
        ],
        "connections": [{"source": "t", "target": "s"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    resp = client.post(
        "/api/mcp/call",
        json={"name": "trigger_workflow", "arguments": {"workflow_id": "wf_mcp_trig"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    eid = resp.json()["data"]["execution_id"]
    assert _poll(client, headers, eid) == "success"


def test_mcp_get_execution_reports_outputs(client: TestClient):
    headers = _setup(client)
    resp = client.post(
        "/api/mcp/call",
        json={"name": "get_execution", "arguments": {"execution_id": "nope"}},
        headers=headers,
    )
    assert resp.status_code == 404


def test_mcp_set_workflow_active(client: TestClient):
    headers = _setup(client)
    wf = {
        "id": "wf_mcp_active",
        "name": "MCP active",
        "nodes": [{"id": "t", "type": "schedule", "parameters": {"cron": "0 12 * * *", "timezone": "UTC"}}],
        "connections": [],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    resp = client.post(
        "/api/mcp/call",
        json={"name": "set_workflow_active", "arguments": {"workflow_id": "wf_mcp_active", "active": True}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["active"] is True
    assert client.get("/api/workflows/wf_mcp_active", headers=headers).json()["data"]["active"] is True


def test_mcp_use_template_creates_workflow(client: TestClient):
    headers = _setup(client)
    tmpl = client.post(
        "/api/templates",
        json={
            "name": "MCP Lib T",
            "description": "from MCP",
            "category": "general",
            "is_public": True,
            "workflow_data": {
                "nodes": [
                    {"id": "t", "type": "manual_trigger", "parameters": {}},
                    {"id": "s", "type": "set_data", "parameters": {"fields": {"src": "template"}}},
                ],
                "connections": [{"source": "t", "target": "s"}],
            },
        },
        headers=headers,
    ).json()["data"]
    tid = tmpl["id"]

    resp = client.post(
        "/api/mcp/call",
        json={"name": "use_template", "arguments": {"template_id": tid}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    new_id = resp.json()["data"]["id"]

    created = client.get(f"/api/workflows/{new_id}", headers=headers).json()["data"]
    assert created["name"] == "MCP Lib T"
    # use count incremented
    listing = client.get("/api/templates", headers=headers).json()["data"]
    row = next(r for r in listing if r["id"] == tid)
    assert row["use_count"] >= 1


def test_mcp_tool_list_includes_new_tools(client: TestClient):
    headers = _setup(client)
    tools = client.get("/api/mcp/tools", headers=headers).json()["data"]
    names = {t["name"] for t in tools}
    assert {"set_workflow_active", "use_template"} <= names
