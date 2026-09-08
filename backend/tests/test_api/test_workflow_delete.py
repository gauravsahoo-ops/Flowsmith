"""Workflow delete tests (Phase: workflow delete).

The delete is a SOFT delete (deleted_at): the workflow vanishes from
every access path, but the row, its version snapshots, and — critically
— its execution history stay in the database so past runs remain
auditable by the owner. Shares are removed (they cascade per the share
schema) and trigger registrations are reconciled.
"""

from __future__ import annotations

import time

from sqlalchemy import select

from app.db import get_session
from app.models import (
    AuditEvent,
    Execution,
    WebhookTrigger,
    WorkflowRecord,
    WorkflowShare,
    WorkflowVersionRecord,
)
from tests.test_api.conftest import auth_headers, make_workflow, register


def _setup(client):
    return auth_headers(register(client)["token"])


def _run_and_poll(client, headers, wf_id):
    resp = client.post(f"/api/workflows/{wf_id}/run", json={}, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return execution_id, data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {data['status']}")


# ----------------------------------------------------------------------
# Successful delete
# ----------------------------------------------------------------------


def test_successful_delete_hides_workflow_everywhere(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)

    assert client.delete("/api/workflows/wf_1", headers=headers).status_code == 204

    # Gone from the active list and from every access path.
    assert client.get("/api/workflows/wf_1", headers=headers).status_code == 404
    listed = client.get("/api/workflows", headers=headers).json()["data"]
    assert listed == []
    assert client.put("/api/workflows/wf_1", json=make_workflow(), headers=headers).status_code == 404
    assert client.patch("/api/workflows/wf_1/active", json={"active": True}, headers=headers).status_code == 404
    assert client.post("/api/workflows/wf_1/run", json={}, headers=headers).status_code == 404
    assert client.get("/api/workflows/wf_1/versions", headers=headers).status_code == 404
    assert client.post("/api/workflows/wf_1/rollback", json={"version": 1}, headers=headers).status_code == 404

    # The row is soft-deleted, not removed.
    db = get_session()
    try:
        rec = db.get(WorkflowRecord, "wf_1")
        assert rec is not None
        assert rec.deleted_at is not None
        assert rec.active is False
    finally:
        db.close()


# ----------------------------------------------------------------------
# Authorization
# ----------------------------------------------------------------------


def test_unauthorized_delete_is_404(client):
    owner = register(client, "owner@del.com")
    stranger = register(client, "stranger@del.com")
    owner_headers = auth_headers(owner["token"])
    client.post("/api/workflows", json=make_workflow(), headers=owner_headers)

    # A stranger (existence hidden)…
    assert client.delete("/api/workflows/wf_1", headers=auth_headers(stranger["token"])).status_code == 404

    # …and a shared editor/viewer cannot delete either.
    client.post(
        "/api/workflows/wf_1/shares",
        json={"email": "stranger@del.com", "permission": "edit"},
        headers=owner_headers,
    )
    assert client.delete("/api/workflows/wf_1", headers=auth_headers(stranger["token"])).status_code == 404

    # The workflow still exists for the owner.
    assert client.get("/api/workflows/wf_1", headers=owner_headers).status_code == 200


def test_delete_unknown_workflow_404(client):
    headers = _setup(client)
    assert client.delete("/api/workflows/ghost", headers=headers).status_code == 404


def test_delete_already_deleted_workflow_404(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    assert client.delete("/api/workflows/wf_1", headers=headers).status_code == 204
    # Deleting again is 404, not a silent no-op.
    assert client.delete("/api/workflows/wf_1", headers=headers).status_code == 404


# ----------------------------------------------------------------------
# Related resources: versions, executions, shares, triggers, audit
# ----------------------------------------------------------------------


def test_delete_with_versions_preserves_snapshots(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    wf = make_workflow()
    wf["name"] = "Renamed"
    assert client.put("/api/workflows/wf_1", json=wf, headers=headers).status_code == 200
    assert client.get("/api/workflows/wf_1", headers=headers).json()["data"]["version"] == 2

    assert client.delete("/api/workflows/wf_1", headers=headers).status_code == 204

    # Version snapshots are preserved (audit) but no longer reachable.
    db = get_session()
    try:
        versions = db.scalars(
            select(WorkflowVersionRecord).where(WorkflowVersionRecord.workflow_id == "wf_1")
        ).all()
        assert {v.version for v in versions} == {1, 2}
    finally:
        db.close()
    assert client.get("/api/workflows/wf_1/versions", headers=headers).status_code == 404
    assert client.post("/api/workflows/wf_1/rollback", json={"version": 1}, headers=headers).status_code == 404


def test_delete_with_execution_history_preserves_audit(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    execution_id, data = _run_and_poll(client, headers, "wf_1")
    assert data["status"] == "success"

    assert client.delete("/api/workflows/wf_1", headers=headers).status_code == 204

    # The execution row survives with its snapshot…
    db = get_session()
    try:
        rec = db.get(Execution, execution_id)
        assert rec is not None
        assert rec.workflow_id == "wf_1"
        assert rec.workflow_data is not None
    finally:
        db.close()

    # …and the owner can still open it (auditable history)…
    assert client.get(f"/api/executions/{execution_id}", headers=headers).status_code == 200
    assert client.get(f"/api/executions/{execution_id}/trace", headers=headers).status_code == 200
    # …but it is gone from the execution list (workflow is gone) and the
    # workflow can no longer be re-run or retried from it.
    history = client.get("/api/executions", headers=headers).json()["data"]
    assert all(e["id"] != execution_id for e in history)
    assert client.post(f"/api/executions/{execution_id}/retry", json={}, headers=headers).status_code == 404

    # Non-owners cannot view the owner's preserved history.
    stranger = register(client, "ghost@del.com")
    assert client.get(f"/api/executions/{execution_id}", headers=auth_headers(stranger["token"])).status_code == 404


def test_delete_removes_shares(client):
    owner = register(client, "own@del.com")
    editor = register(client, "ed@del.com")
    owner_headers = auth_headers(owner["token"])
    client.post("/api/workflows", json=make_workflow(), headers=owner_headers)
    client.post(
        "/api/workflows/wf_1/shares",
        json={"email": "ed@del.com", "permission": "edit"},
        headers=owner_headers,
    )

    assert client.delete("/api/workflows/wf_1", headers=owner_headers).status_code == 204

    db = get_session()
    try:
        shares = db.scalars(
            select(WorkflowShare).where(WorkflowShare.workflow_id == "wf_1")
        ).all()
        assert shares == []
    finally:
        db.close()
    editor_headers = auth_headers(editor["token"])
    assert client.get("/api/workflows/wf_1", headers=editor_headers).status_code == 404
    assert client.get("/api/workflows", headers=editor_headers).json()["data"] == []


def test_delete_deactivates_webhook_trigger(client):
    headers = _setup(client)
    wf = make_workflow()
    wf["nodes"].append(
        {"id": "hook", "type": "webhook", "parameters": {"path": "/del-test-webhook-path-0123456789abcdef"}, "settings": {}}
    )
    wf["connections"] = [
        {"source": "trigger", "target": "transform"},
        {"source": "transform", "target": "hook"},
    ]
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201
    assert client.patch("/api/workflows/wf_1/active", json={"active": True}, headers=headers).status_code == 200

    db = get_session()
    try:
        assert db.scalars(
            select(WebhookTrigger).where(WebhookTrigger.workflow_id == "wf_1")
        ).all() != []
    finally:
        db.close()

    assert client.delete("/api/workflows/wf_1", headers=headers).status_code == 204

    db = get_session()
    try:
        assert db.scalars(
            select(WebhookTrigger).where(WebhookTrigger.workflow_id == "wf_1")
        ).all() == []
    finally:
        db.close()


def test_delete_is_audited(client):
    headers = _setup(client)
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    assert client.delete("/api/workflows/wf_1", headers=headers).status_code == 204

    db = get_session()
    try:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.target_id == "wf_1")
        ).all()
        assert any(e.action == "workflow.delete" for e in events)
    finally:
        db.close()