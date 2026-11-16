"""Durable ApprovalRequest integration for human_approval pauses.

Proves the bridge between the legacy execution pause (``pause_state``) and
the first-class approval record:

1. A pause creates exactly one pending ``ApprovalRequest`` with the run,
   node, workflow, tenant, approvers, quorum, risk tier and TTL metadata.
2. Resuming the execution with approval records an approved decision on
   that request; rejecting records a rejected decision.
3. The execution row remains the resume authority: repeated resume still
   conflicts, decisions taken through the approvals API do not auto-resume,
   and a missing durable record does not block the existing resume path.
"""

from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import delete

from app.db import get_session
from app.models import ApprovalRequest
from tests.test_api.conftest import auth_headers, register

APPROVAL_TIMEOUT_HOURS = 24


def _poll(client, execution_id, headers, timeout_s=15.0):
    status = "unknown"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/executions/{execution_id}", headers=headers).json()
        if "data" in body:
            status = body["data"]["status"]
            if status not in ("running", "queued", "cancelling"):
                return body["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {status}")


def _approval_workflow(wf_id: str, approvers: list[int] | None = None) -> dict:
    return {
        "id": wf_id,
        "name": "Approval integration",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "gate",
                "type": "human_approval",
                "parameters": {
                    "message": "Ship it?",
                    "approvers": approvers or [],
                    "timeout_hours": APPROVAL_TIMEOUT_HOURS,
                },
            },
            {
                "id": "after",
                "type": "set_data",
                "parameters": {"fields": {"result": "done"}},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "gate"},
            {"source": "gate", "target": "after"},
        ],
        "settings": {},
    }


def _run_and_wait_for_approval(client, headers, wf_id: str) -> str:
    run = client.post(f"/api/workflows/{wf_id}/run", json={"data": {"value": "ok"}}, headers=headers).json()["data"]
    data = _poll(client, run["execution_id"], headers)
    assert data["status"] == "waiting_approval", data.get("error")
    assert data["node_statuses"]["gate"] == "waiting_approval"
    return run["execution_id"]


def _pending_for(client, headers, execution_id: str) -> list[dict]:
    body = client.get("/api/approvals", headers=headers).json()
    return [row for row in body["data"] if row["run_id"] == execution_id]


def _wait_for_pending(client, headers, execution_id: str, timeout_s=10.0) -> dict:
    """The pause status commits just before the approval record; poll both."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pending = _pending_for(client, headers, execution_id)
        if pending:
            assert len(pending) == 1, pending
            return pending[0]
        time.sleep(0.05)
    raise AssertionError(f"no durable approval request for execution {execution_id}")


def _all_for(client, headers, execution_id: str) -> list[dict]:
    rows: dict[str, dict] = {}
    for decision_status in ("pending", "approved", "rejected", "expired", "cancelled"):
        body = client.get(f"/api/approvals?status={decision_status}", headers=headers).json()
        for row in body["data"]:
            if row["run_id"] == execution_id:
                rows[row["id"]] = row
    return list(rows.values())


def test_pause_creates_one_durable_pending_request(client):
    registered = register(client)
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    wf_id = "wf_approval_integration_created"
    assert (
        client.post(
            "/api/workflows",
            json=_approval_workflow(wf_id, approvers=[user_id]),
            headers=headers,
        ).status_code
        == 201
    )

    execution_id = _run_and_wait_for_approval(client, headers, wf_id)

    request = _wait_for_pending(client, headers, execution_id)
    assert request["node_id"] == "gate"
    assert request["workflow_id"] == wf_id
    assert request["status"] == "pending"
    assert request["risk_tier"] == 2
    assert request["quorum"] == 1
    assert request["separation_of_duties"] is False
    assert request["summary"] == "Workflow approval gate"
    assert request["reason"] == "Ship it?"
    assert request["requested_by"] == user_id
    assert request["approvers"] == [user_id]

    created_at = datetime.fromisoformat(request["created_at"])
    expires_at = datetime.fromisoformat(request["expires_at"])
    ttl_hours = (expires_at - created_at).total_seconds() / 3600
    assert APPROVAL_TIMEOUT_HOURS - 0.1 <= ttl_hours <= APPROVAL_TIMEOUT_HOURS + 0.1

    # Listing is read-only: no duplicate pending record appears.
    assert len(_pending_for(client, headers, execution_id)) == 1


def test_resume_approved_records_approval_once(client):
    registered = register(client)
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    wf_id = "wf_approval_integration_approved"
    assert (
        client.post(
            "/api/workflows",
            json=_approval_workflow(wf_id, approvers=[user_id]),
            headers=headers,
        ).status_code
        == 201
    )

    execution_id = _run_and_wait_for_approval(client, headers, wf_id)
    request_id = _wait_for_pending(client, headers, execution_id)["id"]

    resumed = client.post(f"/api/executions/{execution_id}/resume", json={"approved": True}, headers=headers)
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success", data.get("error")

    detail = client.get(f"/api/approvals/{request_id}", headers=headers).json()["data"]
    assert detail["status"] == "approved"
    assert detail["decided_by"] == user_id
    assert detail["decision"]["latest"]["approved"] is True

    # Replaying the resume still conflicts and never creates another request.
    replay = client.post(f"/api/executions/{execution_id}/resume", json={"approved": True}, headers=headers)
    assert replay.status_code == 409
    assert _pending_for(client, headers, execution_id) == []
    all_requests = _all_for(client, headers, execution_id)
    assert len(all_requests) == 1
    assert all_requests[0]["id"] == request_id
    assert all_requests[0]["status"] == "approved"


def test_resume_rejected_records_rejection(client):
    registered = register(client)
    headers = auth_headers(registered["token"])
    wf_id = "wf_approval_integration_rejected"
    assert client.post("/api/workflows", json=_approval_workflow(wf_id), headers=headers).status_code == 201

    execution_id = _run_and_wait_for_approval(client, headers, wf_id)
    request_id = _wait_for_pending(client, headers, execution_id)["id"]

    resumed = client.post(f"/api/executions/{execution_id}/resume", json={"approved": False}, headers=headers)
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "failed"
    assert data["error"]["code"] == "APPROVAL_REJECTED"

    detail = client.get(f"/api/approvals/{request_id}", headers=headers).json()["data"]
    assert detail["status"] == "rejected"
    assert detail["decided_by"] == registered["user"]["id"]
    assert detail["decision"]["latest"]["approved"] is False
    assert _pending_for(client, headers, execution_id) == []


def test_approvals_api_decision_does_not_auto_resume(client):
    registered = register(client)
    headers = auth_headers(registered["token"])
    wf_id = "wf_approval_integration_api_decide"
    assert client.post("/api/workflows", json=_approval_workflow(wf_id), headers=headers).status_code == 201

    execution_id = _run_and_wait_for_approval(client, headers, wf_id)
    request_id = _wait_for_pending(client, headers, execution_id)["id"]

    decided = client.post(
        f"/api/approvals/{request_id}/decide",
        json={"approved": True, "nonce": "integration-nonce-1"},
        headers=headers,
    )
    assert decided.status_code == 200, decided.text

    # The approvals API never resumes the execution in this slice.
    still_paused = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
    assert still_paused["status"] == "waiting_approval"

    # The execution endpoint remains the resume authority.
    resumed = client.post(f"/api/executions/{execution_id}/resume", json={"approved": True}, headers=headers)
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"
    assert len(_all_for(client, headers, execution_id)) == 1


def test_resume_continues_without_durable_record(client):
    registered = register(client)
    headers = auth_headers(registered["token"])
    wf_id = "wf_approval_integration_missing_record"
    assert client.post("/api/workflows", json=_approval_workflow(wf_id), headers=headers).status_code == 201

    execution_id = _run_and_wait_for_approval(client, headers, wf_id)
    _wait_for_pending(client, headers, execution_id)

    # Simulate a pause created before the durable broker existed.
    db = get_session()
    try:
        db.execute(delete(ApprovalRequest).where(ApprovalRequest.run_id == execution_id))
        db.commit()
    finally:
        db.close()

    resumed = client.post(f"/api/executions/{execution_id}/resume", json={"approved": True}, headers=headers)
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success"
    assert _all_for(client, headers, execution_id) == []

def test_durable_decision_is_authoritative_on_resume(client):
    registered = register(client)
    headers = auth_headers(registered["token"])
    wf_id = "wf_approval_integration_authoritative"
    assert client.post("/api/workflows", json=_approval_workflow(wf_id), headers=headers).status_code == 201

    execution_id = _run_and_wait_for_approval(client, headers, wf_id)
    request_id = _wait_for_pending(client, headers, execution_id)["id"]

    decided = client.post(
        f"/api/approvals/{request_id}/decide",
        json={"approved": True, "nonce": "integration-nonce-authoritative"},
        headers=headers,
    )
    assert decided.status_code == 200, decided.text

    # A conflicting resume payload must not override the durable decision.
    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": False},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success", data.get("error")

    detail = client.get(f"/api/approvals/{request_id}", headers=headers).json()["data"]
    assert detail["status"] == "approved"

def test_cancel_waiting_execution_closes_pending_approval(client):
    registered = register(client)
    headers = auth_headers(registered["token"])
    wf_id = "wf_approval_integration_cancel_cleanup"
    assert client.post("/api/workflows", json=_approval_workflow(wf_id), headers=headers).status_code == 201

    execution_id = _run_and_wait_for_approval(client, headers, wf_id)
    request = _wait_for_pending(client, headers, execution_id)

    cancelled = client.post(
        f"/api/executions/{execution_id}/cancel", json={}, headers=headers
    )
    assert cancelled.status_code == 200, cancelled.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "cancelled"

    detail = client.get(f"/api/approvals/{request['id']}", headers=headers).json()["data"]
    assert detail["status"] == "cancelled"
    assert detail["decision"]["reason"] == "execution_cancelled"

    # A terminal run cannot be resurrected through the approval inbox.
    decided = client.post(
        f"/api/approvals/{request['id']}/decide",
        json={"approved": True, "nonce": "cancelled-run-nonce"},
        headers=headers,
    )
    assert decided.status_code == 409, decided.text
