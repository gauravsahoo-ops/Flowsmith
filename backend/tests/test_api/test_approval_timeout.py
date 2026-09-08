"""Approval timeout auto-reject + decision metadata (Phase 36).

- fail_expired_approvals(): waiting executions past their timeout window
  fail with APPROVAL_TIMEOUT; timeout_hours=0 means "never expires".
- Resumed runs record WHO approved/rejected and WHEN in
  execution.results["approval"].
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from app.db import get_session
from app.models import Execution
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
    raise AssertionError("execution did not finish")


def _approval_workflow(client, headers):
    wf = {
        "id": "wf_apptimeout",
        "name": "Approval timeout",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "gate", "type": "human_approval",
             "parameters": {"message": "Decide!", "timeout_hours": 1}},
            {"id": "after", "type": "set_data", "parameters": {"fields": {"done": "yes"}}},
        ],
        "connections": [
            {"source": "trigger", "target": "gate"},
            {"source": "gate", "target": "after"},
        ],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201


def _wait_for_approval(client, headers, wf_id="wf_apptimeout") -> str:
    run = client.post(f"/api/workflows/{wf_id}/run", json={}, headers=headers).json()["data"]
    data = _poll(client, run["execution_id"], headers)
    assert data["status"] == "waiting_approval"
    return run["execution_id"]


def test_approval_timeout_auto_rejects(client):
    from app.maintenance import fail_expired_approvals

    headers = auth_headers(register(client)["token"])
    _approval_workflow(client, headers)
    eid = _wait_for_approval(client, headers)

    # Simulate that the pause happened 2h ago (timeout is 1h).
    db = get_session()
    try:
        rec = db.get(Execution, eid)
        rec.pause_state = {
            **(rec.pause_state or {}),
            "paused_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        }
        db.commit()
        expired = fail_expired_approvals(db, datetime.now(UTC))
        assert expired == 1
    finally:
        db.close()

    data = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
    assert data["status"] == "failed"
    assert data["error"]["code"] == "APPROVAL_TIMEOUT"
    assert data["pause_state"] is None


def test_zero_timeout_never_expires(client):
    from app.maintenance import fail_expired_approvals

    headers = auth_headers(register(client)["token"])
    wf = {
        "id": "wf_apptimeout0",
        "name": "No timeout",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "gate", "type": "human_approval",
             "parameters": {"timeout_hours": 0}},
        ],
        "connections": [{"source": "trigger", "target": "gate"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201
    eid = _wait_for_approval(client, headers, wf_id="wf_apptimeout0")

    db = get_session()
    try:
        rec = db.get(Execution, eid)
        rec.pause_state = {
            **(rec.pause_state or {}),
            # paused far in the past, but timeout_hours=0 => never expires
            "paused_at": (datetime.now(UTC) - timedelta(days=365)).isoformat(),
        }
        db.commit()
        assert fail_expired_approvals(db, datetime.now(UTC)) == 0
    finally:
        db.close()

    data = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
    assert data["status"] == "waiting_approval"


def test_resume_records_decision_metadata(client):
    headers = auth_headers(register(client)["token"])
    _approval_workflow(client, headers)
    eid = _wait_for_approval(client, headers)

    before = datetime.now(UTC).replace(tzinfo=None)
    resp = client.post(f"/api/executions/{eid}/resume", json={"approved": True}, headers=headers)
    assert resp.status_code == 200
    data = _poll(client, eid, headers)
    after = datetime.now(UTC).replace(tzinfo=None)

    assert data["status"] == "success"
    stamp = data["results"]["approval"]
    assert stamp["approved"] is True
    assert stamp["node_id"] == "gate"
    decided = datetime.fromisoformat(stamp["approved_at"]).replace(tzinfo=None)
    assert before <= decided <= after
