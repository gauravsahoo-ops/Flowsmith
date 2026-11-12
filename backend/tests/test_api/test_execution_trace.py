"""Execution trace tests (M8): step-by-step run log with inputs/outputs/errors."""

from __future__ import annotations

import time

import pytest

from tests.test_api.conftest import auth_headers, make_workflow, register

pytestmark = pytest.mark.usefixtures("slow_node")

WF_OK = make_workflow()

WF_CHAIN = {
    "id": "wf_chain",
    "name": "Chain",
    "nodes": [
        {"id": "a", "type": "set_data", "parameters": {"fields": {"x": 1}}},
        {"id": "b", "type": "set_data", "parameters": {"fields": {"y": "{{ $json.x }}"}}},
    ],
    "connections": [
        {"source": "a", "target": "b"},
    ],
    "settings": {},
}

WF_FAIL_DOWNSTREAM = {
    "id": "wf_fail2",
    "name": "Fails downstream",
    "nodes": [
        {"id": "boom", "type": "http_request", "parameters": {
            "url": "http://127.0.0.1:9/nope", "method": "GET",
        }},
        {"id": "tail", "type": "set_data", "parameters": {"fields": {"z": "never"}}},
    ],
    "connections": [{"source": "boom", "target": "tail"}],
    "settings": {},
}

WF_HUGE = {
    "id": "wf_huge",
    "name": "Huge payload",
    "nodes": [
        {"id": "big", "type": "set_data", "parameters": {
            "fields": {"blob": "x" * 5000},
        }},
    ],
    "connections": [],
    "settings": {},
}


def _setup(client):
    return auth_headers(register(client)["token"])


def _run(client, headers, wf, data=None):
    client.post("/api/workflows", json=wf, headers=headers)
    resp = client.post(f"/api/workflows/{wf['id']}/run", json={"data": data} if data else {}, headers=headers)
    assert resp.status_code == 202
    return resp.json()["data"]["execution_id"]


def _wait_done(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time")


def test_trace_records_successful_steps(client):
    headers = _setup(client)
    execution_id = _run(client, headers, WF_CHAIN)
    detail = _wait_done(client, execution_id, headers)
    assert detail["status"] == "success"
    assert detail["trace"] is not None

    body = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    steps = body["data"]["steps"]
    assert [s["node_id"] for s in steps] == ["a", "b"]
    assert [s["status"] for s in steps] == ["success", "success"]

    a, b = steps
    assert a["node_type"] == "set_data"
    assert a["inputs"] == [{}]
    assert a["outputs"]["main"][0]["x"] == 1
    assert a["duration_ms"] >= 0
    assert "T" in a["started_at"]

    # b saw a's output on its input (expressions resolve against it)
    assert b["inputs"][0]["x"] == 1
    assert b["outputs"]["main"][0]["y"] == 1


def test_trace_records_error_and_skipped_steps(client):
    headers = _setup(client)
    execution_id = _run(client, headers, WF_FAIL_DOWNSTREAM)
    detail = _wait_done(client, execution_id, headers)
    assert detail["status"] == "failed"

    steps = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()["data"]["steps"]
    boom, tail = steps
    assert boom["status"] == "error"
    assert boom["error"]["code"] in ("HTTP_REQUEST_FAILED", "NODE_ERROR")
    assert boom["node_id"] == "boom"
    assert tail["status"] == "skipped"
    assert tail["note"] is not None
    assert tail["inputs"] is None


def test_trace_truncates_huge_payloads(client):
    headers = _setup(client)
    execution_id = _run(client, headers, WF_HUGE)
    _wait_done(client, execution_id, headers)

    steps = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()["data"]["steps"]
    blob = steps[0]["outputs"]["main"][0]["blob"]
    assert len(blob) == 501  # 500 chars + ellipsis


def test_trace_404_for_other_user(client):
    headers = _setup(client)
    execution_id = _run(client, headers, WF_OK)
    _wait_done(client, execution_id, headers)

    token_b = register(client, email="b2@b.com", password="Password123!")["token"]
    assert client.get(
        f"/api/executions/{execution_id}/trace", headers=auth_headers(token_b)
    ).status_code == 404


def test_preview_trace_keeps_every_per_record_step(client):
    """The 50-row preview cap must not hide records after the 49th step."""
    wf = {
        "id": "wf_per_record_preview",
        "name": "Per-record preview",
        "nodes": [
            {
                "id": "split",
                "type": "split",
                "parameters": {"fieldToSplitOut": "items", "include": "allOtherFields"},
            },
            {"id": "enrich", "type": "set_data", "parameters": {"fields": {"seen": True}}},
        ],
        "connections": [{"source": "split", "target": "enrich"}],
        "settings": {},
    }
    headers = _setup(client)
    items = [{"email": f"person{i}@example.com", "idx": i} for i in range(150)]
    execution_id = _run(client, headers, wf, data={"items": items})
    detail = _wait_done(client, execution_id, headers)
    assert detail["status"] == "success"

    enrich = [step for step in detail["trace"] if step["node_id"] == "enrich"]
    assert len(enrich) == 150
    assert enrich[0]["item_index"] == 1
    assert enrich[-1]["item_index"] == 150
    assert enrich[99]["note"] == "Record 100/150."
    assert enrich[99]["inputs"]["main"][0]["email"] == "person99@example.com"

    trace_steps = client.get(
        f"/api/executions/{execution_id}/trace", headers=headers
    ).json()["data"]["steps"]
    trace_enrich = [step for step in trace_steps if step["node_id"] == "enrich"]
    assert len(trace_enrich) == 150


def test_preview_trace_rows_has_explicit_overall_cap():
    from app.api.executions import TRACE_PREVIEW_MAX_ROWS, _preview_trace_rows

    rows = [
        {"node_id": f"n{i}", "node_type": "set_data", "status": "success", "started_at": "2026-01-01T00:00:00Z"}
        for i in range(TRACE_PREVIEW_MAX_ROWS + 3)
    ]
    preview = _preview_trace_rows(rows)

    assert len(preview) == TRACE_PREVIEW_MAX_ROWS + 1
    assert preview[-1]["node_id"] == "__trace_truncated__"
    assert "3 further steps are stored" in preview[-1]["note"]


def test_execution_duration_handles_naive_datetimes():
    """SQLite returns naive timestamps; duration calculation must not crash."""
    from datetime import datetime

    from app.api.executions import _to_dict
    from app.models import Execution

    rec = Execution(
        id="exec_naive",
        workflow_id="wf_naive",
        status="success",
        started_at=datetime(2026, 1, 1, 0, 0, 0),
        finished_at=datetime(2026, 1, 1, 0, 0, 1),
    )
    payload = _to_dict(rec)
    assert payload["duration_ms"] == 1000.0
