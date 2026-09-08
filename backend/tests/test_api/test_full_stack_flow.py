"""End-to-end regression: the M5 acceptance workflow
Manual Trigger -> Set Data -> IF / Condition -> Set Data
run through the real stack: API -> job queue -> worker -> DAG engine
-> database -> execution history/trace. Guards the exact path a UI-created
workflow takes (spec 9, 13, 14, 24, 25, 51).

No engine stubs: the embedded consumer claims the job and the real
executor runs the DAG, so I/O propagation, branching and persistence are
all exercised against the production code path.
"""

from __future__ import annotations

import time

from tests.test_api.conftest import auth_headers, register


def _branch_workflow(workflow_id: str = "wf_branch") -> dict:
    return {
        "id": workflow_id,
        "name": "Branch",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "enrich", "type": "set_data", "parameters": {"fields": {"kind": "{{ $json.kind }}"}}},
            {"id": "if", "type": "if_condition", "parameters": {
                "condition": {"left": "$json.kind", "operator": "equals", "right": "customer"},
            }},
            {"id": "finalize", "type": "set_data", "parameters": {"fields": {"handled": True}}},
        ],
        "connections": [
            {"source": "trigger", "target": "enrich"},
            {"source": "enrich", "target": "if"},
            {"source": "if", "target": "finalize", "sourceHandle": "true"},
        ],
        "settings": {},
    }


def _poll(client, execution_id, headers, timeout_s=15.0) -> dict:
    deadline = time.monotonic() + timeout_s
    status = "running"
    while time.monotonic() < deadline:
        resp = client.get(f"/api/executions/{execution_id}", headers=headers)
        data = resp.json()["data"]
        status = data["status"]
        if status not in ("running", "queued", "cancelling"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish in time: {status}")


def _run(client, headers, wf_id="wf_branch", data=None):
    resp = client.post(f"/api/workflows/{wf_id}/run", json={"data": data}, headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()["data"]["execution_id"]


def test_acceptance_workflow_full_stack(client):
    headers = auth_headers(register(client)["token"])
    assert client.post("/api/workflows", json=_branch_workflow(), headers=headers).status_code == 201

    execution_id = _run(client, headers, data={"kind": "customer"})
    data = _poll(client, execution_id, headers)

    assert data["status"] == "success"
    assert data["node_statuses"] == {"trigger": "success", "enrich": "success", "if": "success", "finalize": "success"}

    # I/O propagation: enrich merged the trigger input; IF routed on it.
    outputs = data["results"]["outputs"]
    assert outputs["enrich"]["main"] == [{"kind": "customer"}]
    # IF output_by_handle: true branch carries the item, false is empty.
    assert outputs["if"]["true"] == [{"kind": "customer"}]
    assert outputs["if"]["false"] == []
    assert outputs["finalize"]["main"] == [{"kind": "customer", "handled": True}]

    # Persistence: the execution shows up in history with results + trace.
    history = client.get("/api/executions?workflow_id=wf_branch", headers=headers).json()
    assert history["meta"]["total"] == 1
    assert history["data"][0]["id"] == execution_id
    assert history["data"][0]["status"] == "success"

    trace = client.get(f"/api/executions/{execution_id}/trace", headers=headers).json()
    steps = {s["node_id"]: s for s in trace["data"]["steps"]}
    assert set(steps) == {"trigger", "enrich", "if", "finalize"}
    assert all(s["status"] == "success" for s in steps.values())

    items = client.get(f"/api/executions/{execution_id}/items", headers=headers).json()
    assert items["meta"]["total"] == 4


def test_acceptance_workflow_false_branch_skips_downstream(client):
    headers = auth_headers(register(client)["token"])
    assert client.post("/api/workflows", json=_branch_workflow(), headers=headers).status_code == 201

    execution_id = _run(client, headers, data={"kind": "vendor"})
    data = _poll(client, execution_id, headers)

    assert data["status"] == "success"
    assert data["node_statuses"] == {"trigger": "success", "enrich": "success", "if": "success", "finalize": "skipped"}
    assert data["results"]["outputs"]["if"]["true"] == []
    assert data["results"]["outputs"]["if"]["false"] == [{"kind": "vendor"}]
    # Skipped nodes never produce outputs; they are recorded as skipped.
    assert "finalize" not in data["results"]["outputs"]


def test_acceptance_workflow_retry_preserves_snapshot(client):
    headers = auth_headers(register(client)["token"])
    assert client.post("/api/workflows", json=_branch_workflow(), headers=headers).status_code == 201

    first = _run(client, headers, data={"kind": "customer"})
    _poll(client, first, headers)

    retry = client.post(f"/api/executions/{first}/retry", json={}, headers=headers)
    assert retry.status_code == 202
    new_id = retry.json()["data"]["execution_id"]
    assert new_id != first
    data = _poll(client, new_id, headers)
    assert data["status"] == "success"
    assert data["results"]["outputs"]["finalize"]["main"] == [{"kind": "customer", "handled": True}]