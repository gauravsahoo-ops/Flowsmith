"""Execution endpoint tests (spec 51.4): run, list, detail, items, retry, cancel."""

from __future__ import annotations

import time

import pytest

from tests.test_api.conftest import SLOW_TYPE, auth_headers, make_workflow, register

pytestmark = [pytest.mark.timing, pytest.mark.usefixtures("slow_node")]

WF_OK = make_workflow()
WF_FAIL = {
    "id": "wf_fail",
    "name": "Fails",
    "nodes": [
        {"id": "http", "type": "http_request", "parameters": {
            "url": "http://127.0.0.1:9/nope", "method": "GET",
        }},
    ],
    "connections": [],
    "settings": {},
}


@pytest.fixture(autouse=True)
def _slow_node_registered(slow_node):
    pass


def _setup(client):
    return auth_headers(register(client)["token"])


def _poll(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    status = "running"
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        status = resp.json()["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            return resp.json()["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time: {status}")


def test_run_workflow_succeeds(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    resp = client.post("/api/workflows/wf_1/run", json={"data": {"name": "Ada"}}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]

    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"
    assert data["node_statuses"] == {"trigger": "success", "transform": "success"}
    outputs = data["results"]["outputs"]["transform"]["main"]
    assert outputs == [{"greeting": "hi", "name": "Ada"}]


def test_run_without_token_rejected(client):
    assert client.post("/api/workflows/wf_1/run", json={}).status_code == 401


def test_run_missing_workflow_404(client):
    headers = _setup(client)
    assert client.post("/api/workflows/ghost/run", json={}, headers=headers).status_code == 404


def test_run_failing_workflow_records_error(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_FAIL, headers=headers)
    resp = client.post("/api/workflows/wf_fail/run", json={}, headers=headers)
    execution_id = resp.json()["data"]["execution_id"]

    data = _poll(client, execution_id, headers)
    assert data["status"] == "failed"
    assert data["error"]["node_id"] == "http"
    assert data["node_statuses"]["http"] == "error"


def test_list_executions_paginated_and_filtered(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    ids = []
    for _ in range(3):
        run = client.post("/api/workflows/wf_1/run", json={}, headers=headers).json()["data"]
        ids.append(run["execution_id"])
    for execution_id in ids:
        _poll(client, execution_id, headers)
    body = client.get("/api/executions?workflow_id=wf_1&pageSize=2", headers=headers).json()
    assert body["meta"]["total"] == 3
    assert len(body["data"]) == 2
    assert body["data"][0]["status"] == "success"


def test_execution_items_paginated(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={}, headers=headers).json()["data"]
    execution_id = run["execution_id"]
    _poll(client, execution_id, headers)

    body = client.get(f"/api/executions/{execution_id}/items?pageSize=1", headers=headers).json()
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 1
    assert body["data"][0]["status"] == "success"


def test_get_execution_404_for_other_user(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={}, headers=headers).json()["data"]
    execution_id = run["execution_id"]
    _poll(client, execution_id, headers)

    token_b = register(client, email="b@b.com", password="Password123!")["token"]
    assert client.get(f"/api/executions/{execution_id}", headers=auth_headers(token_b)).status_code == 404


def test_retry_recreates_execution_from_snapshot(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_FAIL, headers=headers)
    first = client.post("/api/workflows/wf_fail/run", json={}, headers=headers).json()["data"]
    _poll(client, first["execution_id"], headers)

    retry = client.post(f"/api/executions/{first['execution_id']}/retry", json={}, headers=headers)
    assert retry.status_code == 202
    new_id = retry.json()["data"]["execution_id"]
    assert new_id != first["execution_id"]
    data = _poll(client, new_id, headers)
    assert data["status"] == "failed"
    assert data["workflow_version"] == 1


def test_retry_missing_execution_404(client):
    headers = _setup(client)
    assert client.post("/api/executions/ghost/retry", json={}, headers=headers).status_code == 404


def test_cancel_running_execution(client):
    headers = _setup(client)
    wf = {
        "id": "wf_slow",
        "name": "Slow",
        "nodes": [{"id": "slow", "type": SLOW_TYPE, "parameters": {}}],
        "connections": [],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)
    run = client.post("/api/workflows/wf_slow/run", json={}, headers=headers).json()["data"]
    execution_id = run["execution_id"]

    time.sleep(0.2)
    cancel = client.post(f"/api/executions/{execution_id}/cancel", json={}, headers=headers)
    assert cancel.status_code == 200
    data = _poll(client, execution_id, headers)
    assert data["status"] == "cancelled"


def test_cancel_finished_execution_conflicts(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    run = client.post("/api/workflows/wf_1/run", json={}, headers=headers).json()["data"]
    execution_id = run["execution_id"]
    _poll(client, execution_id, headers)
    assert client.post(f"/api/executions/{execution_id}/cancel", json={}, headers=headers).status_code == 409


def test_workflow_timeout_marks_execution_timeout(client):
    headers = _setup(client)
    wf = {
        "id": "wf_timeout",
        "name": "Timing out",
        "nodes": [{"id": "slow", "type": SLOW_TYPE, "parameters": {}}],
        "connections": [],
        "settings": {"timeout_seconds": 0.3},
    }
    client.post("/api/workflows", json=wf, headers=headers)
    run = client.post("/api/workflows/wf_timeout/run", json={}, headers=headers).json()["data"]
    execution_id = run["execution_id"]

    deadline = time.monotonic() + 15
    status = "running"
    while time.monotonic() < deadline:
        status = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            break
        time.sleep(0.2)
    assert status == "timeout"


# ──────────────────────────────────────────────────────────────────────
# Tests for run-node and run-to-node (Phase 17: node editor modal)
# ──────────────────────────────────────────────────────────────────────

WF_MULTI = {
    "id": "wf_multi",
    "name": "Multi-node",
    "nodes": [
        {"id": "trigger", "type": "manual_trigger", "parameters": {}},
        {"id": "code", "type": "code", "parameters": {"code": "return [{'x': 1}]", "language": "python"}},
        {"id": "http", "type": "http_request", "parameters": {
            "url": "http://127.0.0.1:9/data", "method": "GET",
        }},
        {"id": "set_data", "type": "set_data", "parameters": {"fields": {"greeting": "hi"}}},
    ],
    "connections": [
        {"source": "trigger", "target": "code"},
        {"source": "code", "target": "http"},
        {"source": "http", "target": "set_data"},
    ],
    "settings": {},
}


def test_run_node_standalone_code(client):
    """Execute a single code node in isolation."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_MULTI, headers=headers)
    resp = client.post("/api/workflows/wf_multi/run-node", json={"node_id": "code"}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"
    assert data["node_statuses"]["code"] == "success"


def test_run_node_standalone_trigger(client):
    """Execute a trigger node in isolation."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_MULTI, headers=headers)
    resp = client.post("/api/workflows/wf_multi/run-node", json={"node_id": "trigger"}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"
    assert data["node_statuses"]["trigger"] == "success"


def test_run_node_standalone_set_data(client):
    """Execute a set_data node in isolation."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_MULTI, headers=headers)
    resp = client.post("/api/workflows/wf_multi/run-node", json={"node_id": "set_data"}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"
    assert data["node_statuses"]["set_data"] == "success"


def test_run_node_invalid_node_404(client):
    """Run-node with unknown node_id returns 404."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_MULTI, headers=headers)
    resp = client.post("/api/workflows/wf_multi/run-node", json={"node_id": "ghost"}, headers=headers)
    assert resp.status_code == 404


def test_run_to_node_code(client):
    """Run up to and including the code node (trigger + code run, rest skipped)."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_MULTI, headers=headers)
    resp = client.post("/api/workflows/wf_multi/run-to-node", json={"node_id": "code"}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"
    assert data["node_statuses"]["trigger"] == "success"
    assert data["node_statuses"]["code"] == "success"


def test_run_to_node_set_data(client):
    """Run up to set_data — trigger, code, and http should run."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_MULTI, headers=headers)
    resp = client.post("/api/workflows/wf_multi/run-to-node", json={"node_id": "set_data"}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]
    data = _poll(client, execution_id, headers)
    assert data["status"] in ("success", "failed")
    assert data["node_statuses"]["trigger"] == "success"
    assert data["node_statuses"]["code"] == "success"
    assert data["node_statuses"]["http"] in ("success", "error", "failed")


def test_run_to_node_trigger_only(client):
    """Run-to-node with the trigger means only trigger runs."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_MULTI, headers=headers)
    resp = client.post("/api/workflows/wf_multi/run-to-node", json={"node_id": "trigger"}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"
    assert data["node_statuses"]["trigger"] == "success"


def test_run_to_node_invalid_404(client):
    """Run-to-node with unknown node_id returns 404."""
    headers = _setup(client)
    client.post("/api/workflows", json=WF_MULTI, headers=headers)
    resp = client.post("/api/workflows/wf_multi/run-to-node", json={"node_id": "ghost"}, headers=headers)
    assert resp.status_code == 404


def test_run_node_without_auth_rejected(client):
    """run-node without token returns 401."""
    client.post("/api/workflows", json=WF_MULTI)
    assert client.post("/api/workflows/wf_multi/run-node", json={"node_id": "code"}).status_code == 401


def test_run_to_node_without_auth_rejected(client):
    """run-to-node without token returns 401."""
    client.post("/api/workflows", json=WF_MULTI)
    assert client.post("/api/workflows/wf_multi/run-to-node", json={"node_id": "code"}).status_code == 401