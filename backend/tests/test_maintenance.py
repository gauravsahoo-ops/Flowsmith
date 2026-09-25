"""Retention pruning tests (Phase 11): prune() and the admin endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.maintenance import prune
from app.models import AuditEvent, Execution, WebhookDelivery, WorkflowRecord
from tests.test_api.conftest import auth_headers, register


@pytest.fixture
def client():
    """Empty Postgres DB per test (root conftest truncates before each test)."""
    return TestClient(app)


def _execution(execution_id: str, user_id: int, workflow_id: str, started_at: datetime, status: str = "success", trigger: str = "manual") -> Execution:
    return Execution(
        id=execution_id,
        workflow_id=workflow_id,
        user_id=user_id,
        workflow_version=1,
        workflow_data={},
        trigger=trigger,
        status=status,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1),
    )


def _seed(client, workflow_id: str = "wf_prune", user_id: int = 0) -> None:
    db = get_session()
    try:
        db.add(WorkflowRecord(id=workflow_id, user_id=user_id, name="Prune WF", data={}, active=False))
        old = datetime.now(UTC) - timedelta(days=100)
        recent = datetime.now(UTC) - timedelta(hours=1)
        db.add_all([
            _execution("exec_old", user_id, workflow_id, old),
            _execution("exec_old_webhook", user_id, workflow_id, old, trigger="webhook"),
            _execution("exec_recent", user_id, workflow_id, recent, status="running"),
        ])
        db.add(WebhookDelivery(
            id="dlv_old", workflow_id=workflow_id, user_id=user_id, path="hook-1",
            status="queued", received_at=old, execution_id="exec_old_webhook",
        ))
        db.commit()
    finally:
        db.close()


def test_prune_deletes_old_finished_only(client):
    user = register(client)
    _seed(client, user_id=user["user"]["id"])
    db = get_session()
    try:
        counts = prune(db, datetime.now(UTC) - timedelta(days=30))
        assert counts["executions"] == 2
        assert counts["deliveries"] == 1
        assert counts["running_kept"] == 1
        assert db.get(Execution, "exec_old") is None
        assert db.get(Execution, "exec_old_webhook") is None
        assert db.get(Execution, "exec_recent") is not None
        assert db.get(WebhookDelivery, "dlv_old") is None
    finally:
        db.close()


def test_prune_dry_run_deletes_nothing(client):
    user = register(client)
    _seed(client, user_id=user["user"]["id"])
    db = get_session()
    try:
        counts = prune(db, datetime.now(UTC) - timedelta(days=30), dry_run=True)
        assert counts["executions"] == 2
        assert db.get(Execution, "exec_old") is not None
        assert db.get(WebhookDelivery, "dlv_old") is not None
    finally:
        db.close()


def test_prune_cutoff_keeps_newer_executions(client):
    user = register(client)
    db = get_session()
    try:
        db.add(WorkflowRecord(id="wf_prune", user_id=user["user"]["id"], name="Prune WF", data={}, active=False))
        now = datetime.now(UTC)
        db.add_all([
            _execution("exec_just_now", user["user"]["id"], "wf_prune", now - timedelta(minutes=2)),
            _execution("exec_long_ago", user["user"]["id"], "wf_prune", now - timedelta(days=100)),
        ])
        db.commit()
        counts = prune(db, now - timedelta(days=7))
        assert counts["executions"] == 1  # only the 100-day-old one
        assert db.get(Execution, "exec_just_now") is not None
        assert db.get(Execution, "exec_long_ago") is None
    finally:
        db.close()


def test_admin_prune_endpoint(client):
    user = register(client)
    auth = auth_headers(user["token"])
    other = register(client, email="other@corp.io")
    _seed(client, user_id=user["user"]["id"])

    # Non-admins are forbidden even to preview.
    resp = client.post("/api/admin/maintenance/prune", json={}, headers=auth_headers(other["token"]))
    assert resp.status_code == 403

    # Admin dry run: preview, nothing deleted.
    resp = client.post("/api/admin/maintenance/prune", json={"dry_run": True, "days": 30}, headers=auth)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["dry_run"] is True
    assert body["executions"] == 2
    db = get_session()
    assert db.get(Execution, "exec_old") is not None
    db.close()

    # Admin real prune deletes and writes an audit event.
    resp = client.post("/api/admin/maintenance/prune", json={"dry_run": False, "days": 30}, headers=auth)
    body = resp.json()["data"]
    assert body["dry_run"] is False
    assert body["executions"] == 2
    db = get_session()
    try:
        assert db.get(Execution, "exec_old") is None
        events = db.query(AuditEvent).filter(AuditEvent.target_type == "system").all()
        assert any(ev.action == "admin.prune" for ev in events)
    finally:
        db.close()