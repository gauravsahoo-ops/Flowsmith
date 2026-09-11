"""Human approval end-to-end (Phase 32).

Proves the durable pause/resume contract through the real stack
(API -> queue -> worker -> engine -> node):

1. A run reaching human_approval stops with status waiting_approval —
   the engine must NOT overwrite it with success.
2. Downstream nodes are not executed while paused.
3. The inbox filter (GET /api/executions?status=waiting_approval) lists it.
4. Resume with approved=true replays persisted outputs (the trigger is
   NOT re-executed) and completes downstream nodes.
5. Resume with approved=false fails the run with APPROVAL_REJECTED.
6. Cancelling a waiting execution terminates it.
7. Approver restrictions are enforced (403 for non-listed users).
"""

from __future__ import annotations

import time

import pytest

from tests.test_api.conftest import auth_headers, register


def _poll(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/executions/{execution_id}", headers=headers).json()
        if "data" in body:
            st = body["data"]["status"]
            if st not in ("running", "queued", "cancelling"):
                return body["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {st}")


def _approval_workflow(wf_id="wf_approve"):
    return {
        "id": wf_id,
        "name": "Approval flow",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "gate",
                "type": "human_approval",
                "parameters": {"message": "Ship it?"},
            },
            {
                "id": "after",
                "type": "set_data",
                "parameters": {"fields": {"result": "{{ $node.gate.json.value }}"}},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "gate"},
            {"source": "gate", "target": "after"},
        ],
        "settings": {},
    }


def _run_and_wait_for_approval(client, headers):
    run = client.post(
        "/api/workflows/wf_approve/run", json={"data": {"value": "ok"}}, headers=headers
    ).json()["data"]
    data = _poll(client, run["execution_id"], headers)
    assert data["status"] == "waiting_approval", data.get("error")
    assert data["finished_at"] is None
    # Paused: downstream has not executed
    statuses = data["node_statuses"] or {}
    assert statuses.get("gate") == "waiting_approval"
    assert "after" not in statuses or statuses["after"] == "skipped"
    return run["execution_id"]


def test_pause_then_resume_approved(client):
    headers = auth_headers(register(client)["token"])
    client.post("/api/workflows", json=_approval_workflow(), headers=headers)

    execution_id = _run_and_wait_for_approval(client, headers)

    # The inbox filter lists the paused execution
    body = client.get("/api/executions?status=waiting_approval", headers=headers).json()
    assert any(e["id"] == execution_id for e in body["data"])

    # Resume with approval; the decision rides through the queue
    resp = client.post(f"/api/executions/{execution_id}/resume", json={"approved": True}, headers=headers)
    assert resp.status_code == 200, resp.text
    data = _poll(client, execution_id, headers)

    assert data["status"] == "success", data.get("error")
    outputs = data["results"]["outputs"]["after"]["main"]
    assert outputs == [{"value": "ok", "result": "ok"}]
    # Upstream side effects never re-run: no trigger step in this trace
    steps = {s["node_id"]: s for s in data["trace"]}
    assert "trigger" not in steps
    assert steps["gate"]["status"] == "success"


def test_resume_rejected_fails_run(client):
    headers = auth_headers(register(client)["token"])
    client.post("/api/workflows", json=_approval_workflow(), headers=headers)
    execution_id = _run_and_wait_for_approval(client, headers)

    resp = client.post(f"/api/executions/{execution_id}/resume", json={"approved": False}, headers=headers)
    assert resp.status_code == 200
    data = _poll(client, execution_id, headers)

    assert data["status"] == "failed"
    assert data["error"]["code"] == "APPROVAL_REJECTED"


def test_cancel_waiting_execution(client):
    headers = auth_headers(register(client)["token"])
    client.post("/api/workflows", json=_approval_workflow(), headers=headers)
    execution_id = _run_and_wait_for_approval(client, headers)

    resp = client.post(f"/api/executions/{execution_id}/cancel", json={}, headers=headers)
    assert resp.status_code == 200
    data = _poll(client, execution_id, headers)
    assert data["status"] == "cancelled"


def test_resume_requires_listed_approver(client):
    headers = auth_headers(register(client)["token"])
    wf = _approval_workflow()
    # Restrict approvers to user id 999 (not the owner)
    wf["nodes"][1]["parameters"]["approvers"] = [999]
    client.post("/api/workflows", json=wf, headers=headers)
    execution_id = _run_and_wait_for_approval(client, headers)

    resp = client.post(f"/api/executions/{execution_id}/resume", json={"approved": True}, headers=headers)
    assert resp.status_code == 403


def test_resume_query_param_backward_compat(client):
    """The legacy `approved` query parameter still works."""
    headers = auth_headers(register(client)["token"])
    client.post("/api/workflows", json=_approval_workflow(), headers=headers)
    execution_id = _run_and_wait_for_approval(client, headers)

    resp = client.post(f"/api/executions/{execution_id}/resume?approved=true", headers=headers)
    assert resp.status_code == 200
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"


def test_double_resume_conflicts(client):
    headers = auth_headers(register(client)["token"])
    client.post("/api/workflows", json=_approval_workflow(), headers=headers)
    execution_id = _run_and_wait_for_approval(client, headers)

    first = client.post(f"/api/executions/{execution_id}/resume", json={"approved": True}, headers=headers)
    assert first.status_code == 200
    second = client.post(f"/api/executions/{execution_id}/resume", json={"approved": True}, headers=headers)
    assert second.status_code == 409
    _poll(client, execution_id, headers)
