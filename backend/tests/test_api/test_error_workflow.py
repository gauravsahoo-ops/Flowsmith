"""Global error workflow tests (Batch D): a failed run starts the handler
named by settings.on_error_workflow_id with the failure context; the
original failed record is preserved; no setting/inactive/self handlers
never fire; handler failures never cascade.
"""

from __future__ import annotations

import time

import pytest

from tests.test_api.conftest import auth_headers, register

pytestmark = [pytest.mark.timing]


def _setup(client):
    return auth_headers(register(client)["token"])


def _handler_workflow(workflow_id="wf_err_handler", fail=False):
    nodes = [
        {"id": "trigger", "type": "manual_trigger", "parameters": {}},
        {"id": "seen", "type": "set_data", "parameters": {
            "fields": {
                "code": "{{ $json.error.code }}",
                "failed": "{{ $json.failed_execution_id }}",
            },
        }},
    ]
    if fail:
        nodes.append({"id": "boom", "type": "stop_and_error", "parameters": {}})
        connections = [
            {"source": "trigger", "target": "seen"},
            {"source": "seen", "target": "boom"},
        ]
    else:
        connections = [{"source": "trigger", "target": "seen"}]
    return {
        "id": workflow_id, "name": "ErrHandler", "nodes": nodes,
        "connections": connections, "settings": {},
    }


def _failing_workflow(workflow_id="wf_main", on_error=None):
    settings = {}
    if on_error is not None:
        settings = {"on_error_workflow_id": on_error}
    return {
        "id": workflow_id, "name": "Main", "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "boom", "type": "stop_and_error", "parameters": {}},
        ],
        "connections": [{"source": "trigger", "target": "boom"}],
        "settings": settings,
    }


def _create(client, headers, workflow, active=False):
    resp = client.post("/api/workflows", json=workflow, headers=headers)
    assert resp.status_code == 201, resp.text
    if active:
        resp = client.patch(f"/api/workflows/{workflow['id']}/active", json={"active": True}, headers=headers)
        assert resp.status_code == 200, resp.text


def _poll(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        status = resp.json()["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            return resp.json()["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time")


def _handler_runs(client, headers, handler_id):
    body = client.get(f"/api/executions?workflow_id={handler_id}", headers=headers).json()
    return body["data"]


def test_failing_run_starts_error_handler(client):
    headers = _setup(client)
    _create(client, headers, _handler_workflow(), active=True)
    _create(client, headers, _failing_workflow(on_error="wf_err_handler"))
    run = client.post("/api/workflows/wf_main/run", json={}, headers=headers).json()["data"]
    main = _poll(client, run["execution_id"], headers)
    assert main["status"] == "failed"

    deadline = time.monotonic() + 15.0
    runs = []
    while time.monotonic() < deadline:
        runs = [e for e in _handler_runs(client, headers, "wf_err_handler") if e["trigger"] == "error_handler"]
        if runs and runs[0]["status"] not in ("running", "queued", "cancelling"):
            break
        time.sleep(0.1)
    assert runs, "error handler never ran"
    handler = _poll(client, runs[0]["id"], headers)
    assert handler["status"] == "success"
    seen = handler["results"]["outputs"]["seen"]["main"][0]
    assert seen["failed"] == run["execution_id"]
    assert seen["code"]  # error code propagated


def test_no_setting_no_handler_run(client):
    headers = _setup(client)
    _create(client, headers, _handler_workflow(), active=True)
    _create(client, headers, _failing_workflow())
    run = client.post("/api/workflows/wf_main/run", json={}, headers=headers).json()["data"]
    _poll(client, run["execution_id"], headers)
    assert _handler_runs(client, headers, "wf_err_handler") == []


def test_inactive_handler_never_fires(client):
    headers = _setup(client)
    _create(client, headers, _handler_workflow(), active=False)
    _create(client, headers, _failing_workflow(on_error="wf_err_handler"))
    run = client.post("/api/workflows/wf_main/run", json={}, headers=headers).json()["data"]
    data = _poll(client, run["execution_id"], headers)
    assert data["status"] == "failed"
    assert _handler_runs(client, headers, "wf_err_handler") == []


def test_self_reference_does_not_loop(client):
    headers = _setup(client)
    _create(client, headers, _failing_workflow(workflow_id="wf_loop", on_error="wf_loop"), active=True)
    run = client.post("/api/workflows/wf_loop/run", json={}, headers=headers).json()["data"]
    _poll(client, run["execution_id"], headers)
    time.sleep(1.0)  # let any cascade start
    body = client.get("/api/executions?workflow_id=wf_loop", headers=headers).json()
    assert len(body["data"]) == 1


def test_failing_handler_does_not_cascade(client):
    headers = _setup(client)
    _create(client, headers, _handler_workflow(workflow_id="wf_bad_handler", fail=True), active=True)
    _create(client, headers, _failing_workflow(workflow_id="wf_main2", on_error="wf_bad_handler"))
    run = client.post("/api/workflows/wf_main2/run", json={}, headers=headers).json()["data"]
    _poll(client, run["execution_id"], headers)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        runs = _handler_runs(client, headers, "wf_bad_handler")
        done = [e for e in runs if e["status"] not in ("running", "queued", "cancelling")]
        if done:
            break
        time.sleep(0.1)
    # Exactly one handler run (it failed), never a handler-of-handler.
    body = client.get("/api/executions?workflow_id=wf_bad_handler", headers=headers).json()
    assert len(body["data"]) == 1
    assert body["data"][0]["status"] == "failed"
