"""Global error-workflow tests (Batch D engine hook).

A workflow whose ``settings.on_error_workflow_id`` names another workflow
fires that handler once on failure with the failure context; handler runs
use trigger ``error_handler``, never cascade, and never fire for
test-mode runs.
"""

from __future__ import annotations

import time
import uuid

import pytest

from app.db import get_session
from app.models import Execution
from tests.test_api.conftest import auth_headers, register

pytestmark = pytest.mark.timing


def _setup(client):
    info = register(client, email=f"errwf_{uuid.uuid4().hex[:8]}@test.com")
    return auth_headers(info["token"])


def _make(client, headers, workflow, active=False):
    resp = client.post("/api/workflows", json=workflow, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    if active:
        resp = client.patch(f"/api/workflows/{workflow['id']}/active",
                            json={"active": True}, headers=headers)
        assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _run(client, headers, workflow_id):
    resp = client.post(f"/api/workflows/{workflow_id}/run", json={}, headers=headers)
    assert resp.status_code in (200, 201, 202), resp.text
    return resp.json()["data"]["execution_id"]


def _poll_execution(client, headers, execution_id, timeout_s=20.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("queued", "running", "cancelling"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time")


def _poll_handler_success(client, headers, handler_id, timeout_s=20.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        items = client.get(
            "/api/executions", params={"workflow_id": handler_id}, headers=headers,
        ).json()["data"]
        done = [e for e in items if e["status"] not in ("queued", "running", "cancelling")]
        if done:
            return done[0]
        time.sleep(0.1)
    raise AssertionError("error-handler execution did not finish in time")


def test_error_workflow_fires_with_failure_context(client):
    headers = _setup(client)
    suffix = uuid.uuid4().hex[:8]
    handler_id = f"wf_err_handler_{suffix}"
    main_id = f"wf_err_main_{suffix}"

    _make(client, headers, {
        "id": handler_id,
        "name": "ErrHandler",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "echo", "type": "set_data", "parameters": {
                "mode": "replace",
                "fields": {"got": "{{ $json.failed_execution_id }}"},
            }},
        ],
        "connections": [{"source": "trigger", "target": "echo"}],
        "settings": {},
    }, active=True)
    _make(client, headers, {
        "id": main_id,
        "name": "ErrMain",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "boom", "type": "stop_and_error",
             "parameters": {"error_message": "kaboom-errwf"}},
        ],
        "connections": [{"source": "trigger", "target": "boom"}],
        "settings": {"on_error_workflow_id": handler_id},
    })

    main_exec = _run(client, headers, main_id)
    main_data = _poll_execution(client, headers, main_exec)
    assert main_data["status"] == "failed"

    handler_run = _poll_handler_success(client, headers, handler_id)
    assert handler_run["trigger"] == "error_handler"
    assert handler_run["status"] == "success"

    detail = client.get(f"/api/executions/{handler_run['id']}", headers=headers).json()["data"]
    outputs = (detail["results"] or {}).get("outputs", {})
    assert outputs["echo"]["main"][0]["got"] == main_exec

    db = get_session()
    try:
        rec = db.get(Execution, handler_run["id"])
        trigger_items = rec.trigger_data or []
        assert trigger_items and trigger_items[0]["failed_execution_id"] == main_exec
        assert trigger_items[0]["failed_workflow_id"] == main_id
        assert trigger_items[0]["error"]["message"] == "kaboom-errwf"
    finally:
        db.close()


def test_error_workflow_does_not_cascade(client):
    headers = _setup(client)
    suffix = uuid.uuid4().hex[:8]
    handler_id = f"wf_err_cascade_{suffix}"
    main_id = f"wf_err_cascade_main_{suffix}"

    _make(client, headers, {
        "id": handler_id,
        "name": "ErrCascadeHandler",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "boom", "type": "stop_and_error", "parameters": {}},
        ],
        "connections": [{"source": "trigger", "target": "boom"}],
        "settings": {},
    }, active=True)
    _make(client, headers, {
        "id": main_id,
        "name": "ErrCascadeMain",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "boom", "type": "stop_and_error", "parameters": {}},
        ],
        "connections": [{"source": "trigger", "target": "boom"}],
        "settings": {"on_error_workflow_id": handler_id},
    })

    main_exec = _run(client, headers, main_id)
    assert _poll_execution(client, headers, main_exec)["status"] == "failed"
    handler_run = _poll_handler_success(client, headers, handler_id)
    assert handler_run["status"] == "failed"

    # Single level only: exactly one handler execution exists.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        items = client.get(
            "/api/executions", params={"workflow_id": handler_id}, headers=headers,
        ).json()["data"]
        time.sleep(0.2)
    assert len(items) == 1


def test_error_workflow_skipped_in_test_mode():
    from app.execution_runtime import _maybe_run_error_workflow
    from app.queue import QueueJob

    db = get_session()
    try:
        before = db.query(Execution).count()
        job = QueueJob(
            id="job_errwf_test",
            execution_id="exec_errwf_test",
            payload={
                "workflow_data": {"id": "wf_x", "settings": {"on_error_workflow_id": "wf_handler"}},
                "trigger": "manual",
                "trigger_items": [],
                "user_id": 1,
                "workflow_id": "wf_x",
                "version": 1,
                "_test_run": {"mocks": [], "assertions": []},
            },
        )
        _maybe_run_error_workflow(db, job, "exec_errwf_test", {"code": "X", "message": "y"})
        assert db.query(Execution).count() == before
    finally:
        db.close()
