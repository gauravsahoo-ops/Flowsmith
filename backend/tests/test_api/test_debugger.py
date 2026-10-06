"""Phase 13 workflow-debugger tests.

- trace steps carry structured attempts/retries (engine level)
- sensitive-looking keys are masked before traces/results leave the API
- safe node retry: seeds upstream outputs, re-runs only the failed node,
  rejects non-failed/unknown targets (full stack)
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.engine.errors import NodeExecutionError
from app.engine.executor import execute_workflow
from app.schemas.workflow import Connection, Workflow, WorkflowNode
from tests.test_api.conftest import auth_headers, register

# ----------------------------------------------------------------------
# engine-level: structured retry data
# ----------------------------------------------------------------------

FLAKY_TYPE = "flaky_debug_node"


@pytest.fixture()
def flaky_node():
    from pydantic import BaseModel as _Base

    from app.engine.node_base import BaseNode, NodeContext, NodeResult
    from app.nodes.registry import NODE_REGISTRY

    class FlakyParams(_Base):
        pass

    calls = {"n": 0}

    class FlakyNode(BaseNode[FlakyParams]):
        node_type = FLAKY_TYPE
        display_name = "Flaky (debug test)"
        version = 1
        category = "Test"
        icon = "x"
        parameters_schema = FlakyParams

        async def run(self, ctx: NodeContext, params: Any, input_items: list) -> NodeResult:
            calls["n"] += 1
            if calls["n"] == 1:
                raise NodeExecutionError(
                    "transient boom", code="TRANSIENT", node_id=FLAKY_TYPE, retryable=True,
                )
            return NodeResult(output_items=[{"ok": True}])

    NODE_REGISTRY[FLAKY_TYPE] = FlakyNode
    yield FlakyNode
    NODE_REGISTRY.pop(FLAKY_TYPE, None)


async def test_trace_steps_record_attempts_and_retries(flaky_node):
    wf = Workflow(
        id="wf_dbg",
        name="dbg",
        nodes=[
            WorkflowNode(id="t", type="manual_trigger", parameters={}),
            WorkflowNode(
                id="f",
                type=FLAKY_TYPE,
                parameters={},
                settings={"retry_max_attempts": 2, "retry_backoff_seconds": 0},
            ),
        ],
        connections=[Connection(source="t", target="f")],
    )
    result = await execute_workflow(wf, [{"x": 1}], execution_id="exec_dbg")
    assert result.status == "success"
    step = next(s for s in result.trace if s["node_id"] == "f")
    # Two attempts: one transient failure, then success.
    assert step["retries"] == 1
    assert step["attempts"] == 2


async def test_failed_step_reports_attempts_when_giving_up(flaky_node):
    from app.nodes.registry import NODE_REGISTRY

    # Make every attempt fail.
    cls = NODE_REGISTRY[FLAKY_TYPE]

    async def always_fail(self, ctx, params, input_items):  # noqa: ANN001
        raise NodeExecutionError("permanent", code="NOPE", node_id=FLAKY_TYPE, retryable=True)

    cls.run = always_fail  # type: ignore[method-assign]
    wf = Workflow(
        id="wf_dbg2",
        name="dbg",
        nodes=[
            WorkflowNode(id="f", type=FLAKY_TYPE, parameters={},
                         settings={"retry_max_attempts": 2, "retry_backoff_seconds": 0}),
        ],
        connections=[],
    )
    result = await execute_workflow(wf, [{}], execution_id="exec_dbg2")
    assert result.status == "failed"
    step = result.trace[-1]
    assert step["status"] == "error"
    assert step["attempts"] == 3  # 1 initial + 2 retries
    assert step["retries"] == 2


# ----------------------------------------------------------------------
# API-level: redaction + node retry (full stack)
# ----------------------------------------------------------------------

def _setup(client):
    return auth_headers(register(client)["token"])


def _wait_terminal(client, headers, execution_id, timeout_s=45.0):
    # Generous deadline: full-suite runs execute under heavy machine load
    # and the queue may interleave other jobs first.
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return data
        time.sleep(0.05)
    raise AssertionError("execution did not finish")


def test_secrets_masked_in_execution_and_trace(client):
    """Audit: sensitive-keyed values are redacted in execution + trace API responses."""
    headers = _setup(client)
    resp = client.post("/api/workflows", json={
        "id": "wf_secret",
        "name": "secret leak?",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "leak",
                "type": "set_data",
                "parameters": {"fields": {
                    "api_key": "sk-SUPER-SECRET-1",
                    "password": "hunter2",
                    "note": "totally fine",
                }},
            },
        ],
        "connections": [{"source": "trigger", "target": "leak"}],
        "settings": {},
    }, headers=headers)
    assert resp.status_code == 201, resp.text

    resp = client.post("/api/workflows/wf_secret/run", json={"data": {}}, headers=headers)
    assert resp.status_code == 202, resp.text
    exec_id = resp.json()["data"]["execution_id"]
    data = _wait_terminal(client, headers, exec_id)
    assert data["status"] == "success"

    raw = str(data["results"])
    assert "sk-SUPER-SECRET-1" not in raw
    assert "hunter2" not in raw
    assert "totally fine" in raw
    api_key = data["results"]["outputs"]["leak"]["main"][0]["api_key"]
    assert api_key != "sk-SUPER-SECRET-1" and api_key

    trace_resp = client.get(f"/api/executions/{exec_id}/trace", headers=headers).json()["data"]
    leak_step = next(s for s in trace_resp["steps"] if s["node_id"] == "leak")
    out_item = leak_step["outputs"]["main"][0]
    assert out_item["api_key"] != "sk-SUPER-SECRET-1"
    assert out_item["password"] != "hunter2"
    assert out_item["note"] == "totally fine"


def _create_failing_workflow(client, headers):
    resp = client.post("/api/workflows", json={
        "id": "wf_noderetry",
        "name": "node retry e2e",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "boom", "type": "boom", "parameters": {}},
        ],
        "connections": [{"source": "trigger", "target": "boom"}],
        "settings": {},
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    resp = client.post("/api/workflows/wf_noderetry/run", json={"data": {}}, headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()["data"]["execution_id"]


def test_safe_node_retry_seeds_upstream_and_reruns_only_target(client):
    headers = _setup(client)
    failed_exec = _create_failing_workflow(client, headers)
    data = _wait_terminal(client, headers, failed_exec)
    assert data["status"] == "failed"

    # Retrying a node that did NOT fail is rejected.
    resp = client.post(f"/api/executions/{failed_exec}/retry",
                       json={"node_id": "trigger"}, headers=headers)
    assert resp.status_code == 409

    # Unknown node ids are rejected.
    resp = client.post(f"/api/executions/{failed_exec}/retry",
                       json={"node_id": "nope"}, headers=headers)
    assert resp.status_code == 404

    # Safe node retry: only the failed node re-runs; the trigger's output
    # is seeded (it produces no step in the new execution).
    resp = client.post(f"/api/executions/{failed_exec}/retry",
                       json={"node_id": "boom"}, headers=headers)
    assert resp.status_code == 202, resp.text
    new_exec = resp.json()["data"]["execution_id"]
    assert new_exec != failed_exec

    new_data = _wait_terminal(client, headers, new_exec)
    assert new_data["status"] == "failed"  # boom always fails
    assert new_data["trigger"] == "node_retry"

    step_ids = [s["node_id"] for s in new_data["trace"]]
    assert "trigger" not in step_ids, "seeded upstream must not re-execute"
    assert "boom" in step_ids


def test_full_replay_unchanged_without_node_id(client):
    headers = _setup(client)
    failed_exec = _create_failing_workflow(client, headers)
    _wait_terminal(client, headers, failed_exec)

    resp = client.post(f"/api/executions/{failed_exec}/retry", json=None, headers=headers)
    assert resp.status_code == 202
    new_exec = resp.json()["data"]["execution_id"]
    new_data = _wait_terminal(client, headers, new_exec)
    # Full replay re-executes everything: both nodes appear in the trace.
    step_ids = {s["node_id"] for s in new_data["trace"]}
    assert {"trigger", "boom"} <= step_ids
