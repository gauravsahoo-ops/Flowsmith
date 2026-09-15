"""Dead Letter Queue (DLQ) API tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db import get_session
from app.models import Execution, WorkflowRecord
from tests.test_api.conftest import auth_headers, register


def test_dlq_endpoint_requires_auth(client):
    assert client.get("/api/monitoring/dlq").status_code in (401, 403)


def test_dlq_lists_failed_executions_and_retries(client):
    reg = register(client, email="dlq_user@example.com")
    headers = auth_headers(reg["token"])
    user_id = reg["user"]["id"]

    db = get_session()
    try:
        wf = WorkflowRecord(
            id=str(uuid.uuid4()),
            name="DLQ Test Workflow",
            user_id=user_id,
            active=True,
            data={"nodes": [{"id": "n1", "type": "code"}], "connections": []},
        )
        db.add(wf)

        # Create a successful execution (should NOT appear in DLQ)
        succ_exec = Execution(
            id=str(uuid.uuid4()),
            workflow_id=wf.id,
            user_id=user_id,
            workflow_version=1,
            workflow_data=wf.data,
            status="success",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        # Create a failed execution (SHOULD appear in DLQ)
        fail_exec = Execution(
            id=str(uuid.uuid4()),
            workflow_id=wf.id,
            user_id=user_id,
            workflow_version=1,
            workflow_data=wf.data,
            status="failed",
            error="Out of memory or timeout",
            node_statuses={"n1": "failed"},
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        db.add_all([succ_exec, fail_exec])
        db.commit()
        fail_id = fail_exec.id
    finally:
        db.close()

    # Query DLQ
    resp = client.get("/api/monitoring/dlq", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    item = data[0]
    assert item["id"] == fail_id
    assert item["workflow_name"] == "DLQ Test Workflow"
    assert item["status"] == "failed"
    assert item["error"] == "Out of memory or timeout"
    assert item["failed_nodes"] == ["n1"]

    # Retry the DLQ execution
    retry_resp = client.post(f"/api/monitoring/dlq/{fail_id}/retry", headers=headers)
    assert retry_resp.status_code == 202
    assert "execution_id" in retry_resp.json()["data"]


def test_dlq_tenant_isolation(client):
    user_a = register(client, email="user_a_dlq@example.com")
    user_b = register(client, email="user_b_dlq@example.com")

    db = get_session()
    try:
        wf = WorkflowRecord(
            id=str(uuid.uuid4()),
            name="User A Private Workflow",
            user_id=user_a["user"]["id"],
            active=True,
            data={"nodes": []},
        )
        db.add(wf)
        fail_exec = Execution(
            id=str(uuid.uuid4()),
            workflow_id=wf.id,
            user_id=user_a["user"]["id"],
            workflow_version=1,
            workflow_data=wf.data,
            status="failed",
            error="Private Error",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        db.add(fail_exec)
        db.commit()
    finally:
        db.close()

    # User B checks DLQ — must be empty
    resp_b = client.get("/api/monitoring/dlq", headers=auth_headers(user_b["token"]))
    assert resp_b.status_code == 200
    assert len(resp_b.json()["data"]) == 0

    # User A checks DLQ — sees 1 failed run
    resp_a = client.get("/api/monitoring/dlq", headers=auth_headers(user_a["token"]))
    assert resp_a.status_code == 200
    assert len(resp_a.json()["data"]) == 1
