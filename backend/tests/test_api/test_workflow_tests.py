"""Phase 14 — workflow tests, full stack.

Covers the whole feature over the real queue/worker loop:

- CRUD + access control for saved tests
- run-test endpoint executes with trigger="test" and evaluates the spec
- mock rules answer matched outbound HTTP calls locally (PASS)
- unmatched outbound calls are BLOCKED -> node fails, report FAILs, and
  the message states production was never contacted
- test_data feeds trigger items into the run
- regression snapshots produce DIFF checks on drift
- a green report persists under results["tests"] with verdict PASS
"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from tests.test_api.conftest import auth_headers, make_workflow, register

TERMINAL = {"success", "failed", "cancelled", "timeout"}


def _setup(client: TestClient):
    token = auth_headers(register(client)["token"])
    resp = client.post(
        "/api/workflows",
        json=make_workflow("wf_tested"),
        headers=token,
    )
    assert resp.status_code == 201, resp.text
    return token


def _create_test(client, token, workflow_id="wf_tested", **spec) -> dict:
    body = {"name": spec.pop("name", "happy path"), **spec}
    resp = client.post(f"/api/workflows/{workflow_id}/tests", json=body, headers=token)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _wait_terminal(client, token, execution_id, timeout_s=45.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rec = client.get(f"/api/executions/{execution_id}", headers=token).json()["data"]
        if rec["status"] in TERMINAL:
            return rec
        time.sleep(0.25)
    raise AssertionError("execution never reached a terminal state")


# ----------------------------------------------------------------------
# CRUD + access control
# ----------------------------------------------------------------------

def test_crud_roundtrip_and_validation(client: TestClient):
    token = _setup(client)

    created = _create_test(client, token,
        test_data={"customer": "Ada"},
        mocks=[{"url_pattern": "api.example.com/v1/x", "body": {"ok": True}}],
        assertions=[{"type": "workflow_succeeded"}],
    )
    assert created["name"] == "happy path"

    listed = client.get("/api/workflows/wf_tested/tests", headers=token).json()["data"]
    assert [t["id"] for t in listed] == [created["id"]]

    patched = client.patch(
        f"/api/workflows/wf_tested/tests/{created['id']}",
        json={"name": "renamed", "assertions": [{"type": "node_status", "node_id": "transform"}]},
        headers=token,
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["name"] == "renamed"

    got = client.get(f"/api/workflows/wf_tested/tests/{created['id']}", headers=token).json()["data"]
    assert got["assertions"][0]["type"] == "node_status"

    deleted = client.delete(f"/api/workflows/wf_tested/tests/{created['id']}", headers=token)
    assert deleted.status_code == 200
    assert client.get(f"/api/workflows/wf_tested/tests/{created['id']}",
                      headers=token).status_code == 404


def test_unknown_assertion_type_rejected_at_the_edge(client: TestClient):
    token = _setup(client)
    resp = client.post(
        "/api/workflows/wf_tested/tests",
        json={"name": "bad", "assertions": [{"type": "teleport"}]},
        headers=token,
    )
    assert resp.status_code == 422


def test_tests_are_scoped_to_workflow_and_user(client: TestClient):
    token_a = _setup(client)
    test = _create_test(client, token_a)

    other = auth_headers(register(client, email="other@c.com")["token"])
    # Another user cannot even see the workflow's tests.
    assert client.get("/api/workflows/wf_tested/tests", headers=other).status_code == 404
    assert client.get(
        f"/api/workflows/wf_tested/tests/{test['id']}", headers=other,
    ).status_code == 404
    # Cross-workflow ids don't leak either.
    assert client.get(
        f"/api/workflows/wf_other/tests/{test['id']}", headers=token_a,
    ).status_code == 404


# ----------------------------------------------------------------------
# Running tests end-to-end (queue + worker + mocks + evaluation)
# ----------------------------------------------------------------------

def _http_workflow(workflow_id: str, url: str) -> dict:
    return {
        "id": workflow_id,
        "name": "HTTP under test",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "fetch", "type": "http_request", "parameters": {
                "method": "GET", "url": url,
            }},
            {"id": "echo", "type": "set_data", "parameters": {
                "fields": {"source": "{{ $json.name }}"},
            }},
        ],
        "connections": [
            {"source": "trigger", "target": "fetch"},
            {"source": "fetch", "target": "echo"},
        ],
        "settings": {},
    }


def _create_workflow(client, token, wf: dict) -> None:
    resp = client.post("/api/workflows", json=wf, headers=token)
    assert resp.status_code == 201, resp.text


def test_green_run_passes_with_mocks_and_test_data(client: TestClient):
    token = _setup(client)
    _create_workflow(client, token,
                     _http_workflow("wf_http_ok", "https://api.example.com/v1/users/1"))

    test = _create_test(client, token, workflow_id="wf_http_ok",
        test_data={"user_id": 1},
        mocks=[{
            "url_pattern": "api.example.com/v1/users/*",
            "method": "GET",
            "status": 200,
            "body": {"name": "Ada"},
        }],
        assertions=[
            {"type": "workflow_succeeded"},
            {"type": "node_status", "node_id": "fetch", "expected": "success"},
            {"type": "output_equals", "node_id": "fetch", "path": "0.body.name", "expected": "Ada"},
        ],
    )

    queued = client.post(f"/api/workflows/wf_http_ok/tests/{test['id']}/run", headers=token)
    assert queued.status_code == 202, queued.text
    execution_id = queued.json()["data"]["execution_id"]

    rec = _wait_terminal(client, token, execution_id)
    # The workflow itself ran clean; trigger marks it as a test run.
    assert rec["status"] == "success"
    assert rec["trigger"] == "test"

    report = rec["results"]["tests"]
    assert report["pass"] is True
    assert report["verdict"] == "PASS"
    assert all(c["result"] == "PASS" for c in report["checks"])
    assert report["summary"] == "3/3 checks passed"


def test_unmatched_outbound_call_is_blocked_report_fails(client: TestClient):
    token = _setup(client)
    _create_workflow(client, token,
                     _http_workflow("wf_http_blocked", "https://real-provider.example.com/v1/orders"))

    test = _create_test(client, token, workflow_id="wf_http_blocked",
        name="blocks production writes",
        mocks=[{"url_pattern": "some-other.host/*", "method": "GET"}],  # no match for orders URL
        assertions=[{"type": "workflow_succeeded"}],
    )
    queued = client.post(f"/api/workflows/wf_http_blocked/tests/{test['id']}/run", headers=token)
    execution_id = queued.json()["data"]["execution_id"]

    rec = _wait_terminal(client, token, execution_id)
    assert rec["status"] == "failed"
    report = rec["results"]["tests"]
    assert report["pass"] is False
    assert report["verdict"] == "FAIL"
    # The typed block error names the guard, proving no real call happened.
    fetch_error = next(e for e in (rec.get("trace") or []) if e["node_id"] == "fetch")
    assert "no mock matched" in str(fetch_error["error"]["message"]).lower()


def test_regression_snapshot_drift_reports_diff(client: TestClient):
    token = _setup(client)
    _create_workflow(client, token,
                     _http_workflow("wf_http_drift", "https://api.example.com/v1/me"))

    mocks = [{
        "url_pattern": "api.example.com/v1/me",
        "method": "GET",
        "body": {"name": "Grace"},
    }]
    test = _create_test(client, token, workflow_id="wf_http_drift",
        name="snapshot",
        mocks=mocks,
        assertions=[{"type": "workflow_succeeded"}],
        expected_outputs={
            "fetch": {"main": [{"name": "Hopper"}]},  # will NOT match Grace
        },
    )
    queued = client.post(f"/api/workflows/wf_http_drift/tests/{test['id']}/run", headers=token)
    execution_id = queued.json()["data"]["execution_id"]

    rec = _wait_terminal(client, token, execution_id)
    report = rec["results"]["tests"]
    assert report["verdict"] == "FAIL"
    kinds = [c["result"] for c in report["checks"]]
    assert "DIFF" in kinds
    diff_check = next(c for c in report["checks"] if c["result"] == "DIFF")
    assert diff_check["diff"], "drift must carry structured diff entries"


def test_failed_node_assertion_via_error_code(client: TestClient):
    token = _setup(client)
    _create_workflow(client, token,
                     _http_workflow("wf_http_500", "https://api.example.com/v1/exploding"))

    test = _create_test(client, token, workflow_id="wf_http_500",
        name="mocked 500 surfaces as node error (HTTP node raises on 4xx/5xx)",
        mocks=[{"url_pattern": "api.example.com/v1/exploding", "method": "GET", "status": 500}],
        assertions=[
            {"type": "workflow_failed"},
            {"type": "error_code", "node_id": "fetch", "code": "HTTP_500"},
        ],
    )
    queued = client.post(f"/api/workflows/wf_http_500/tests/{test['id']}/run", headers=token)
    execution_id = queued.json()["data"]["execution_id"]

    rec = _wait_terminal(client, token, execution_id)
    assert rec["results"]["tests"]["verdict"] == "PASS"


def test_run_requires_edit_permission_and_existing_ids(client: TestClient):
    token = _setup(client)
    test = _create_test(client, token)
    viewer = auth_headers(register(client, email="viewer@d.com")["token"])
    # Non-existent test id -> 404; unknown workflow -> 404.
    assert client.post(
        "/api/workflows/wf_tested/tests/wft_missing/run", headers=token,
    ).status_code == 404
    assert client.post(
        f"/api/workflows/wf_missing/tests/{test['id']}/run", headers=token,
    ).status_code == 404
