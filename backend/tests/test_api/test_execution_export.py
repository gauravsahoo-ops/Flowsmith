"""Tests for execution export endpoint (JSON and CSV audit files)."""

from __future__ import annotations

import time
import pytest
from tests.test_api.conftest import auth_headers, make_workflow, register

WF_OK = make_workflow()


def _setup(client):
    return auth_headers(register(client)["token"])


def _poll(client, execution_id, headers, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        status = resp.json()["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            return resp.json()["data"]
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time: {status}")


def test_export_execution_json(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    resp = client.post("/api/workflows/wf_1/run", json={"data": {"name": "AuditTester"}}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]

    _poll(client, execution_id, headers)

    export_resp = client.get(f"/api/executions/{execution_id}/export?format=json", headers=headers)
    assert export_resp.status_code == 200
    assert "application/json" in export_resp.headers.get("content-type", "")
    assert "attachment" in export_resp.headers.get("content-disposition", "")
    body = export_resp.json()
    assert body["id"] == execution_id
    assert "trace" in body
    assert "workflow_data" in body


def test_export_execution_csv(client):
    headers = _setup(client)
    client.post("/api/workflows", json=WF_OK, headers=headers)
    resp = client.post("/api/workflows/wf_1/run", json={"data": {"name": "AuditTester"}}, headers=headers)
    assert resp.status_code == 202
    execution_id = resp.json()["data"]["execution_id"]

    _poll(client, execution_id, headers)

    export_resp = client.get(f"/api/executions/{execution_id}/export?format=csv", headers=headers)
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers.get("content-type", "")
    assert "attachment" in export_resp.headers.get("content-disposition", "")
    csv_text = export_resp.text
    assert "step_index,node_id,node_type,status" in csv_text
    assert "trigger" in csv_text
    assert "transform" in csv_text
