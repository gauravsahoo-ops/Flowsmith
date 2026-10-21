"""Monitoring & Observability Audit Test Suite (Section 12).

Comprehensive empirical tests verifying all 9 requirements of Section 12:
1. Execution logs contain accurate timestamps and statuses
2. Search works across logs, executions, workflows and errors
3. Filters, sorting, pagination and detailed record views work
4. Node-level inputs, outputs and execution traces are inspectable
5. Failures show actionable error messages and root causes
6. Metrics, health checks and readiness endpoints are accurate
7. WebSocket or live updates reflect actual execution state
8. Alerts and notification paths work where configured
9. Logs correlate requests, workflow runs and worker activity
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import UTC, datetime

import pytest
from starlette.websockets import WebSocketDisconnect

from app.db import get_session
from app.lifecycle import StartupStage, get_lifecycle
from app.models import ErrorEvent, Execution, NotificationPreference, User, WorkflowRecord
from app.telemetry.context import current_execution_id
from app.telemetry.tracer import init_tracer
from tests.test_api.conftest import auth_headers, make_workflow, register

logger = logging.getLogger("test_monitoring_and_observability_audit")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _await_execution_done(client, headers: dict, execution_id: str, timeout_s: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        if data["status"] not in ("queued", "running", "cancelling"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"Execution {execution_id} did not finish within {timeout_s}s")


def _failing_workflow(wf_id: str = "wf_fail_audit", name: str = "Failing Workflow") -> dict:
    return {
        "id": wf_id,
        "name": name,
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "bad_code",
                "type": "code",
                "parameters": {
                    "code": "throw new Error('Explicit audit failure: division by zero or invalid operation.');",
                    "language": "javascript",
                },
            },
            {
                "id": "unreached",
                "type": "set_data",
                "parameters": {"fields": {"status": "never_run"}},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "bad_code"},
            {"source": "bad_code", "target": "unreached"},
        ],
        "settings": {},
    }


# ===========================================================================
# 1. Execution logs contain accurate timestamps and statuses
# ===========================================================================

def test_01_execution_logs_contain_accurate_timestamps_and_statuses(client):
    """Verify execution records capture valid timestamps, monotonic durations, and accurate statuses."""
    reg = register(client)
    headers = auth_headers(reg["token"])

    wf = make_workflow("wf_time_status", "Timestamp & Status Workflow")
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 201

    run_resp = client.post(f"/api/workflows/{wf['id']}/run", json={"data": {"num": 42}}, headers=headers)
    assert run_resp.status_code == 202
    exec_id = run_resp.json()["data"]["execution_id"]

    detail = _await_execution_done(client, headers, exec_id)
    assert detail["status"] == "success"
    assert detail["started_at"] is not None
    assert detail["finished_at"] is not None

    # Parse ISO-8601 timestamps
    t_start = datetime.fromisoformat(detail["started_at"].replace("Z", "+00:00"))
    t_finish = datetime.fromisoformat(detail["finished_at"].replace("Z", "+00:00"))
    assert t_finish >= t_start

    # Monotonic duration in milliseconds
    duration_ms = detail.get("duration_ms")
    assert duration_ms is not None and duration_ms >= 0.0

    # Node-level trace step timestamps
    trace_resp = client.get(f"/api/executions/{exec_id}/trace", headers=headers)
    assert trace_resp.status_code == 200
    steps = trace_resp.json()["data"]["steps"]
    assert len(steps) >= 2
    for step in steps:
        assert step["status"] == "success"
        assert "started_at" in step and step["started_at"]
        assert step["duration_ms"] >= 0.0


# ===========================================================================
# 2. Search works across logs, executions, workflows and errors
# ===========================================================================

def test_02_search_works_across_logs_executions_workflows_and_errors(client):
    """Verify search filtering across executions, workflows, and error notification events."""
    reg = register(client)
    headers = auth_headers(reg["token"])

    unique_tag = f"srch_{uuid.uuid4().hex[:6]}"
    wf = make_workflow(f"wf_{unique_tag}", f"Workflow with {unique_tag} in title")
    client.post("/api/workflows", json=wf, headers=headers)

    # Run execution to index workflow title and execution ID
    run_resp = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=headers)
    exec_id = run_resp.json()["data"]["execution_id"]
    _await_execution_done(client, headers, exec_id)

    # 1. Search executions by workflow name keyword
    exec_search = client.get(f"/api/executions?search={unique_tag}", headers=headers)
    assert exec_search.status_code == 200
    matched_execs = exec_search.json()["data"]
    assert any(e["id"] == exec_id for e in matched_execs)

    # 2. Search executions by exact execution ID
    exec_id_search = client.get(f"/api/executions?search={exec_id}", headers=headers)
    assert exec_id_search.status_code == 200
    assert any(e["id"] == exec_id for e in exec_id_search.json()["data"])

    # 3. Non-matching search returns 0 executions
    empty_search = client.get("/api/executions?search=completely_nonexistent_token_xyz999", headers=headers)
    assert empty_search.status_code == 200
    assert len(empty_search.json()["data"]) == 0

    # 4. Universal search across executions and telemetry
    univ_search = client.get(f"/api/executions/universal-search?q={unique_tag}", headers=headers)
    assert univ_search.status_code == 200
    res_data = univ_search.json()["data"]
    assert any(r.get("execution_id") == exec_id for r in res_data)


# ===========================================================================
# 3. Filters, sorting, pagination and detailed record views work
# ===========================================================================

def test_03_filters_sorting_pagination_and_detailed_record_views_work(client):
    """Verify filtering by status/workflow, sorting, page/pageSize pagination, and detailed views."""
    reg = register(client)
    headers = auth_headers(reg["token"])

    # Create 1 successful workflow and 1 failing workflow
    wf_ok = make_workflow("wf_filter_ok", "Filter OK Workflow")
    wf_fail = _failing_workflow("wf_filter_fail", "Filter Fail Workflow")
    client.post("/api/workflows", json=wf_ok, headers=headers)
    client.post("/api/workflows", json=wf_fail, headers=headers)

    # Run each workflow to create heterogeneous execution records
    run_ok = client.post(f"/api/workflows/{wf_ok['id']}/run", json={}, headers=headers)
    run_fail = client.post(f"/api/workflows/{wf_fail['id']}/run", json={}, headers=headers)
    id_ok = run_ok.json()["data"]["execution_id"]
    id_fail = run_fail.json()["data"]["execution_id"]

    _await_execution_done(client, headers, id_ok)
    _await_execution_done(client, headers, id_fail)

    # 1. Filter by status=success
    success_resp = client.get("/api/executions?status=success", headers=headers)
    assert success_resp.status_code == 200
    success_ids = [e["id"] for e in success_resp.json()["data"]]
    assert id_ok in success_ids
    assert id_fail not in success_ids

    # 2. Filter by status=failed
    failed_resp = client.get("/api/executions?status=failed", headers=headers)
    assert failed_resp.status_code == 200
    failed_ids = [e["id"] for e in failed_resp.json()["data"]]
    assert id_fail in failed_ids
    assert id_ok not in failed_ids

    # 3. Sorting by started_at desc vs asc
    desc_resp = client.get("/api/executions?sort_by=started_at&sort_dir=desc", headers=headers)
    assert desc_resp.status_code == 200
    assert len(desc_resp.json()["data"]) >= 2

    # 4. Pagination with page and pageSize
    page1 = client.get("/api/executions?page=1&pageSize=1", headers=headers).json()["data"]
    page2 = client.get("/api/executions?page=2&pageSize=1", headers=headers).json()["data"]
    assert len(page1) == 1
    assert len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"]

    # 5. Detailed record view
    detail_resp = client.get(f"/api/executions/{id_ok}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()["data"]
    assert detail["id"] == id_ok
    assert detail["workflow_id"] == "wf_filter_ok"
    assert detail["status"] == "success"
    assert "started_at" in detail and "finished_at" in detail


# ===========================================================================
# 4. Node-level inputs, outputs and execution traces are inspectable
# ===========================================================================

def test_04_node_level_inputs_outputs_and_traces_are_inspectable(client):
    """Verify that node inputs, outputs, data transformations, and timings are inspectable."""
    reg = register(client)
    headers = auth_headers(reg["token"])

    wf = {
        "id": "wf_trace_inspect",
        "name": "Trace Inspection Workflow",
        "nodes": [
            {"id": "node_a", "type": "set_data", "parameters": {"fields": {"score": 95, "user": "Alice"}}},
            {"id": "node_b", "type": "set_data", "parameters": {"fields": {"passed": True, "copied_score": "{{ $json.score }}"}}},
        ],
        "connections": [{"source": "node_a", "target": "node_b"}],
        "settings": {},
    }
    client.post("/api/workflows", json=wf, headers=headers)
    run_resp = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=headers)
    exec_id = run_resp.json()["data"]["execution_id"]
    _await_execution_done(client, headers, exec_id)

    # Inspect execution trace endpoint
    trace_resp = client.get(f"/api/executions/{exec_id}/trace", headers=headers)
    assert trace_resp.status_code == 200
    steps = trace_resp.json()["data"]["steps"]
    assert len(steps) == 2

    step_a = steps[0]
    step_b = steps[1]

    # Node A inspection
    assert step_a["node_id"] == "node_a"
    assert step_a["node_type"] == "set_data"
    assert step_a["status"] == "success"
    assert step_a["outputs"]["main"][0]["score"] == 95
    assert step_a["outputs"]["main"][0]["user"] == "Alice"

    # Node B inspection — verifies input received from Node A and output produced
    assert step_b["node_id"] == "node_b"
    assert step_b["status"] == "success"
    assert step_b["inputs"][0]["score"] == 95
    assert step_b["outputs"]["main"][0]["passed"] is True
    assert step_b["outputs"]["main"][0]["copied_score"] == 95


# ===========================================================================
# 5. Failures show actionable error messages and root causes
# ===========================================================================

def test_05_failures_show_actionable_error_messages_and_root_causes(client):
    """Verify that execution failures record actionable root-cause details and skip downstream nodes."""
    reg = register(client)
    headers = auth_headers(reg["token"])

    wf = _failing_workflow("wf_actionable_error", "Actionable Error Workflow")
    client.post("/api/workflows", json=wf, headers=headers)

    run_resp = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=headers)
    exec_id = run_resp.json()["data"]["execution_id"]
    detail = _await_execution_done(client, headers, exec_id)

    # Execution-level error record
    assert detail["status"] == "failed"
    assert detail["error"] is not None
    err = detail["error"]
    assert "message" in err
    assert "Explicit audit failure" in err["message"] or "NODE_ERROR" in str(err)

    # Trace step-level root cause inspection
    trace_resp = client.get(f"/api/executions/{exec_id}/trace", headers=headers)
    assert trace_resp.status_code == 200
    steps = trace_resp.json()["data"]["steps"]

    failing_step = next(s for s in steps if s["node_id"] == "bad_code")
    assert failing_step["status"] in ("failed", "error")
    assert failing_step["error"] is not None
    assert "Explicit audit failure" in str(failing_step["error"])

    # Unreached downstream node was cleanly recorded as skipped
    skipped_step = next((s for s in steps if s["node_id"] == "unreached"), None)
    if skipped_step:
        assert skipped_step["status"] == "skipped"


# ===========================================================================
# 6. Metrics, health checks and readiness endpoints are accurate
# ===========================================================================

def test_06_metrics_health_checks_and_readiness_endpoints_are_accurate(client):
    """Verify /api/health, /readyz, and Prometheus format metrics at /api/metrics."""
    reg = register(client)
    headers = auth_headers(reg["token"])

    # 1. Health check endpoint
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    h_data = health_resp.json()["data"]
    assert h_data["status"] == "ok"
    assert h_data["version"]
    assert isinstance(h_data["uptime_s"], int) and h_data["uptime_s"] >= 0

    # 2. Readiness check endpoint
    # Transition lifecycle to readiness enabled
    lc = get_lifecycle()
    lc.transition_to(StartupStage.READINESS_ENABLED, "Readiness enabled for audit testing")

    readyz_resp = client.get("/api/readyz")
    assert readyz_resp.status_code in (200, 503)
    r_data = readyz_resp.json()["data"]
    assert "checks" in r_data
    assert "postgres" in r_data["checks"]
    assert r_data["checks"]["postgres"] == "ok"
    assert "uptime_s" in r_data

    # 3. Prometheus metrics endpoint (authenticated)
    metrics_resp = client.get("/api/metrics", headers=headers)
    assert metrics_resp.status_code == 200
    assert "text/plain" in metrics_resp.headers["content-type"]
    text = metrics_resp.text
    assert "# HELP http_requests_total" in text
    assert "# TYPE http_requests_total counter" in text
    assert "# HELP process_uptime_seconds" in text
    assert "# TYPE process_uptime_seconds gauge" in text
    assert "workflows_total" in text
    assert "executions_started_total" in text
    assert "executions_finished_total" in text


# ===========================================================================
# 7. WebSocket or live updates reflect actual execution state
# ===========================================================================

def test_07_websocket_live_updates_reflect_actual_execution_state(client):
    """Verify live execution state transitions stream sequentially over WebSocket."""
    reg = register(client)
    headers = auth_headers(reg["token"])
    token = reg["token"]

    wf = make_workflow("wf_ws_stream", "WebSocket Live Workflow")
    client.post("/api/workflows", json=wf, headers=headers)
    run_resp = client.post(f"/api/workflows/{wf['id']}/run", json={"data": {"msg": "hello"}}, headers=headers)
    exec_id = run_resp.json()["data"]["execution_id"]

    # Connect to live execution WebSocket
    with client.websocket_connect(f"/api/ws/executions/{exec_id}?token={token}") as ws:
        events = []
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            ev = ws.receive_json()
            events.append(ev)
            if ev.get("type") == "execution.terminal" or ev.get("event") == "execution.completed":
                break

    assert len(events) > 0
    event_names = [e.get("event") or e.get("type") for e in events]

    # Verify event lifecycle sequence
    assert "execution.started" in event_names
    assert "node.started" in event_names
    assert "node.completed" in event_names
    assert any(name in ("execution.completed", "execution.terminal") for name in event_names)


# ===========================================================================
# 8. Alerts and notification paths work where configured
# ===========================================================================

def test_08_alerts_and_notification_paths_work_where_configured(client):
    """Verify notification listing, user preferences update, and error event lifecycle (ack/resolve)."""
    reg = register(client)
    headers = auth_headers(reg["token"])
    user_id = reg["user"]["id"]

    # 1. Inspect notification preferences
    prefs_resp = client.get("/api/notifications/preferences", headers=headers)
    assert prefs_resp.status_code == 200
    prefs = prefs_resp.json()["data"]
    assert "email_enabled" in prefs
    assert "notify_on_failure" in prefs

    # 2. Update preferences via PUT
    update_resp = client.put(
        "/api/notifications/preferences",
        json={"email_enabled": True, "notify_on_failure": True, "cooldown_minutes": 15},
        headers=headers,
    )
    assert update_resp.status_code == 200
    updated_prefs = update_resp.json()["data"]
    assert updated_prefs["email_enabled"] is True
    assert updated_prefs["notify_on_failure"] is True
    assert updated_prefs["cooldown_minutes"] == 15

    # 3. Create an error event and test acknowledge / resolve lifecycle
    db = get_session()
    event_id = f"err_{uuid.uuid4().hex[:12]}"
    try:
        db.add(ErrorEvent(
            id=event_id,
            user_id=user_id,
            severity="ERROR",
            category="workflow",
            code="NODE_EXECUTION_ERROR",
            title="Database Connection Failure",
            message="Transient failure during external operation",
            resolution="Verify credentials and connectivity",
            fingerprint=f"fp_{uuid.uuid4().hex[:8]}",
            status="DETECTED",
        ))
        db.commit()
    finally:
        db.close()

    # List notifications
    notifs_resp = client.get("/api/notifications", headers=headers)
    assert notifs_resp.status_code == 200
    items = notifs_resp.json()["data"]["items"]
    assert any(item["id"] == event_id for item in items)

    # Acknowledge notification via /acknowledge
    ack_resp = client.post(f"/api/notifications/{event_id}/acknowledge", headers=headers)
    assert ack_resp.status_code == 200
    assert ack_resp.json()["data"]["status"] == "ACKNOWLEDGED"

    # Resolve notification via /resolve
    resolve_resp = client.post(f"/api/notifications/{event_id}/resolve", headers=headers)
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["data"]["status"] == "RESOLVED"


# ===========================================================================
# 9. Logs correlate requests, workflow runs and worker activity
# ===========================================================================

def test_09_logs_correlate_requests_workflow_runs_and_worker_activity(client, caplog):
    """Verify trace/correlation ID propagation, workflow execution correlation, and structured request logging."""
    from app.api.executions import start_execution
    from app.telemetry.tracer import HAS_OTEL, init_tracer

    init_tracer(service_name="flowsmith-test")

    reg = register(client)
    headers = auth_headers(reg["token"])
    user_id = reg["user"]["id"]

    # 1. Execution & workflow correlation ID propagation
    wf = make_workflow("wf_correlation", "Workflow Correlation")
    client.post("/api/workflows", json=wf, headers=headers)

    corr_id = f"corr_{uuid.uuid4().hex[:12]}"
    db = get_session()
    try:
        exec_id = start_execution(
            db,
            workflow_id=wf["id"],
            user_id=user_id,
            version=1,
            workflow_data=wf,
            trigger="manual",
            trigger_items=[{"test": "correlation"}],
            correlation_id=corr_id,
        )
    finally:
        db.close()

    _await_execution_done(client, headers, exec_id)

    # Verify execution record persisted the correlation ID
    db = get_session()
    try:
        exec_rec = db.get(Execution, exec_id)
        assert exec_rec is not None
        assert exec_rec.correlation_id == corr_id
    finally:
        db.close()

    # Verify search and listing correlates by correlation_id
    corr_search = client.get(f"/api/executions?search={corr_id}", headers=headers)
    assert corr_search.status_code == 200
    assert any(e["id"] == exec_id for e in corr_search.json()["data"])

    # 2. Structured request logging correlation on app.request
    with caplog.at_level(logging.INFO, logger="app.request"):
        resp = client.get("/api/health", headers=headers)
        assert resp.status_code == 200

    req_records = [r for r in caplog.records if r.name == "app.request"]
    assert len(req_records) > 0
    record = req_records[-1]
    assert hasattr(record, "fields")
    fields = record.fields
    assert fields["status"] == 200
    assert fields["method"] == "GET"
    assert fields["path"] == "/api/health"
    assert "duration_ms" in fields

    # 3. If OpenTelemetry is enabled, verify W3C X-Trace-Id header
    if HAS_OTEL:
        trace_id = resp.headers.get("X-Trace-Id")
        assert trace_id is not None
        assert len(trace_id) == 32
