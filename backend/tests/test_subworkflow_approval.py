"""Durable nested sub-workflow approvals (Phase 1).

A database-sourced awaited child runs on a deterministic checkpoint
``Execution`` row. When the child pauses (human gate or gated agent tool),
the parent pauses with a public-only descriptor; the root ``ApprovalRequest``
belongs to the parent execution. Resuming the parent re-enters the child with
its persisted outputs so completed side effects are not repeated.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.agents.tool_execution import ToolApprovalRequired
from app.db import get_session
from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, EmptyParams, NodeContext, NodeResult
from app.models import ApprovalRequest, Execution
from app.nodes.human_approval import HumanApprovalNode, HumanApprovalParams
from app.nodes.registry import register
from app.nodes.sub_workflow import (
    SubWorkflowNode,
    SubWorkflowParams,
    child_execution_id,
)
from tests.test_api.conftest import auth_headers, register as register_user


# ---------------------------------------------------------------------------
# A counting side-effect node: proves resume never replays completed work.
# ---------------------------------------------------------------------------

_COUNTER = {"value": 0}
SIDE_EFFECT_TYPE = "subwf_count_side_effect"


@register
class _CountingSideEffectNode(BaseNode[EmptyParams]):
    node_type = SIDE_EFFECT_TYPE
    display_name = "Sub-workflow side effect counter"
    version = 1
    description = "Increments a process-local counter once per execution."
    category = "Test"
    icon = "test"
    parameters_schema = EmptyParams

    async def run(
        self, ctx: NodeContext, params: EmptyParams, input_items: list[dict[str, Any]]
    ) -> NodeResult:
        _COUNTER["value"] += 1
        return NodeResult(
            output_items=[
                {**item, "side_effect_count": _COUNTER["value"]} for item in input_items
            ]
        )


@pytest.fixture(autouse=True)
def _reset_side_effect_counter():
    _COUNTER["value"] = 0
    yield
    _COUNTER["value"] = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(node_id: str = "sub") -> NodeContext:
    return NodeContext(
        execution_id="exec_unit_parent",
        workflow_id="wf_unit_parent",
        node_id=node_id,
        logger=logging.getLogger("test.subworkflow_approval"),
        http_client=httpx.AsyncClient(),
    )


def _human_child(child_id: str, user_id: int) -> dict[str, Any]:
    return {
        "id": child_id,
        "name": "Approval child",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "side", "type": SIDE_EFFECT_TYPE, "parameters": {}},
            {
                "id": "gate",
                "type": "human_approval",
                "parameters": {
                    "message": "Approve the child?",
                    "approvers": [user_id],
                    "timeout_hours": 24,
                },
            },
            {
                "id": "child_after",
                "type": "set_data",
                "parameters": {"fields": {"child_done": True}},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "side"},
            {"source": "side", "target": "gate"},
            {"source": "gate", "target": "child_after"},
        ],
        "settings": {},
    }


def _conditional_human_child(
    child_id: str, user_id: int, *, gate_on_value: str
) -> dict[str, Any]:
    """Child where only one input item hits the human gate.

    The IF routes on ``$json.value``; non-matching items bypass the gate so a
    multi-item onceForEach run can complete without a second approval.
    """
    return {
        "id": child_id,
        "name": "Conditional approval child",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "side", "type": SIDE_EFFECT_TYPE, "parameters": {}},
            {
                "id": "route",
                "type": "if_condition",
                "parameters": {
                    "conditions": [
                        {
                            "id": "gate_item",
                            "left": "{{$json.value}}",
                            "operator": "is equal to",
                            "right": gate_on_value,
                            "combinator": "AND",
                        }
                    ],
                    "combinator": "AND",
                },
            },
            {
                "id": "gate",
                "type": "human_approval",
                "parameters": {
                    "message": "Approve this item?",
                    "approvers": [user_id],
                    "timeout_hours": 24,
                },
            },
            {
                "id": "after_gated",
                "type": "set_data",
                "parameters": {"fields": {"child_done": True, "gated": True}},
            },
            {
                "id": "after_bypass",
                "type": "set_data",
                "parameters": {"fields": {"child_done": True, "bypassed": True}},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "side"},
            {"source": "side", "target": "route"},
            {"source": "route", "target": "gate", "sourceHandle": "true"},
            {"source": "gate", "target": "after_gated"},
            {"source": "route", "target": "after_bypass", "sourceHandle": "false"},
        ],
        "settings": {},
    }


def _parent_workflow(
    parent_id: str, child_id: str, *, mode: str = "onceWithAll"
) -> dict[str, Any]:
    return {
        "id": parent_id,
        "name": "Approval parent",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sub",
                "type": "sub_workflow",
                "parameters": {
                    "source": "database",
                    "workflow_selector": "id",
                    "workflow_id": child_id,
                    "mode": mode,
                    "options": {"waitForSubWorkflowCompletion": True},
                    "data": {},
                },
            },
            {
                "id": "after",
                "type": "set_data",
                "parameters": {"fields": {"parent_done": True}},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "sub"},
            {"source": "sub", "target": "after"},
        ],
        "settings": {},
    }


def _agent_child(child_id: str) -> dict[str, Any]:
    return {
        "id": child_id,
        "name": "Agent approval child",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "agent",
                "type": "ai_agent",
                "parameters": {
                    "instructions": "Insert rows when asked.",
                    "input": "Insert the row",
                    "tools": ["datatable_insert_row"],
                    "memory_type": "none",
                    "model": "builtin",
                    "allow_builtin_fallback": True,
                },
            },
            {
                "id": "child_after",
                "type": "set_data",
                "parameters": {
                    "fields": {"agent_answer": "{{ $node.agent.json.final_answer }}"}
                },
            },
        ],
        "connections": [
            {"source": "trigger", "target": "agent"},
            {"source": "agent", "target": "child_after"},
        ],
        "settings": {},
    }


def _tool_call(name: str = "datatable_insert_row") -> dict[str, Any]:
    return {
        "id": "call_sub_1",
        "function": {
            "name": name,
            "arguments": json.dumps({"row": {"name": "Ada"}}),
        },
    }


def _poll(client, execution_id: str, headers: dict[str, str], timeout_s: float = 25.0) -> dict:
    status = "unknown"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/executions/{execution_id}", headers=headers).json()
        if "data" in body:
            data = body["data"]
            status = data["status"]
            if status not in ("running", "queued", "cancelling"):
                return data
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not finish: {status}")


def _create_workflow(client, headers, workflow: dict) -> None:
    created = client.post("/api/workflows", json=workflow, headers=headers)
    assert created.status_code == 201, created.text


def _run(
    client,
    headers,
    workflow_id: str,
    data: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> str:
    response = client.post(
        f"/api/workflows/{workflow_id}/run",
        json={"data": data if data is not None else {"value": "ok"}},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["execution_id"]


def _approve(
    client, headers, execution_id: str, *, approved: bool = True
) -> dict[str, Any]:
    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": approved},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    return _poll(client, execution_id, headers)


def _row_snapshot(row: Execution) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "parent_execution_id": row.parent_execution_id,
        "trigger": row.trigger,
        "status": row.status,
        "pause_state": dict(row.pause_state or {}),
        "results": row.results or {},
        "trace": row.trace or [],
        "node_statuses": dict(row.node_statuses or {}),
        "error": row.error,
        "finished_at": row.finished_at,
    }


def _child_snapshot(parent_execution_id: str) -> dict[str, Any] | None:
    with get_session() as db:
        row = db.scalar(
            select(Execution).where(
                Execution.parent_execution_id == parent_execution_id,
                Execution.trigger == "sub_workflow",
            )
        )
        return _row_snapshot(row) if row is not None else None


def _child_row(child_id: str) -> dict[str, Any] | None:
    with get_session() as db:
        row = db.get(Execution, child_id)
        return _row_snapshot(row) if row is not None else None


def _child_rows(parent_execution_id: str) -> list[dict[str, Any]]:
    with get_session() as db:
        rows = db.scalars(
            select(Execution)
            .where(
                Execution.parent_execution_id == parent_execution_id,
                Execution.trigger == "sub_workflow",
            )
            .order_by(Execution.id)
        ).all()
        return [_row_snapshot(row) for row in rows]


def _approval_rows(run_id: str) -> list[dict[str, Any]]:
    with get_session() as db:
        rows = db.scalars(
            select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)
        ).all()
        return [
            {
                "id": row.id,
                "run_id": row.run_id,
                "node_id": row.node_id,
                "status": row.status,
                "workflow_id": row.workflow_id,
            }
            for row in rows
        ]


def _setup_human_child(client, headers, user_id: int, suffix: str) -> tuple[str, str]:
    child_id = f"wf_sub_child_{suffix}"
    parent_id = f"wf_sub_parent_{suffix}"
    _create_workflow(client, headers, _human_child(child_id, user_id))
    _create_workflow(client, headers, _parent_workflow(parent_id, child_id))
    return parent_id, child_id


def _pause_parent(client, headers, parent_id: str) -> tuple[str, dict]:
    execution_id = _run(client, headers, parent_id)
    data = _poll(client, execution_id, headers)
    assert data["status"] == "waiting_approval", data.get("error")
    return execution_id, data


# ---------------------------------------------------------------------------
# Pause: child checkpoint + root-owned request
# ---------------------------------------------------------------------------


def test_parent_pause_creates_child_checkpoint_and_root_request(client):
    registered = register_user(client, email="subwf_pause@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, child_id = _setup_human_child(client, headers, user_id, "pause")

    execution_id, data = _pause_parent(client, headers, parent_id)

    assert data["finished_at"] is None
    pause = data["pause_state"]
    assert pause["type"] == "sub_workflow"
    assert pause["node_id"] == "sub"
    assert pause["child_workflow_id"] == child_id
    assert pause["child_node_id"] == "gate"
    assert pause["child_pause_type"] == "human_approval"
    assert pause["message"] == "Approve the child?"
    assert pause["approvers"] == [user_id]
    assert pause["risk_tier"] == 2
    assert pause["mode"] == "onceWithAll"
    assert pause["depth"] == 1
    # Public metadata only: never child results, trace or encrypted state.
    assert "state" not in pause
    assert "outputs" not in pause
    assert "trace" not in pause

    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["parent_execution_id"] == execution_id
    assert child["trigger"] == "sub_workflow"
    assert child["workflow_id"] == child_id
    assert child["status"] == "waiting_approval"
    assert child["pause_state"]["node_id"] == "gate"
    assert child["pause_state"]["type"] == "human_approval"
    assert child["id"] == pause["child_execution_id"]
    assert pause["child_execution_id"].startswith("sub_")
    # Upstream child work completed; downstream did not run.
    assert "side" in (child["results"].get("outputs") or {})
    assert "child_after" not in (child["results"].get("outputs") or {})
    assert child["node_statuses"].get("gate") == "waiting_approval"
    assert "child_after" not in child["node_statuses"]
    assert _COUNTER["value"] == 1

    # Parent downstream did not run either.
    assert data["node_statuses"].get("sub") == "waiting_approval"
    assert "after" not in data["node_statuses"]
    assert all(step["node_id"] != "after" for step in data["trace"])

    # Exactly one root-owned request; no request keyed to the child run.
    root_requests = _approval_rows(execution_id)
    assert len(root_requests) == 1
    assert root_requests[0]["node_id"] == "sub"
    assert root_requests[0]["status"] == "pending"
    assert root_requests[0]["workflow_id"] == parent_id
    assert root_requests[0]["id"] == pause["approval_id"]
    assert _approval_rows(child["id"]) == []


# ---------------------------------------------------------------------------
# Resume: approval, rejection, and persisted-success reuse
# ---------------------------------------------------------------------------


def test_approve_resumes_child_without_duplicate_side_effect(client):
    registered = register_user(client, email="subwf_approve@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, child_id = _setup_human_child(client, headers, user_id, "approve")

    execution_id, _paused = _pause_parent(client, headers, parent_id)
    assert _COUNTER["value"] == 1

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)

    assert data["status"] == "success", data.get("error")
    # The upstream child side effect ran exactly once.
    assert _COUNTER["value"] == 1
    sub_items = data["results"]["outputs"]["sub"]["main"]
    assert sub_items[0]["side_effect_count"] == 1
    assert sub_items[0]["child_done"] is True
    assert data["results"]["outputs"]["after"]["main"][0]["parent_done"] is True

    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["id"] == _paused["pause_state"]["child_execution_id"]
    assert child["workflow_id"] == child_id
    assert child["status"] == "success"
    assert child["pause_state"] == {}
    assert child["error"] is None
    assert child["finished_at"] is not None
    assert child["node_statuses"].get("gate") == "success"
    assert child["node_statuses"].get("child_after") == "success"
    # Persisted outputs survive the resume even though "side" was not rerun.
    assert "side" in (child["results"].get("outputs") or {})


def test_reject_propagates_approval_rejected_not_subworkflow_failed(client):
    registered = register_user(client, email="subwf_reject@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "reject")

    execution_id, _paused = _pause_parent(client, headers, parent_id)
    assert _COUNTER["value"] == 1

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": False},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)

    assert data["status"] == "failed"
    assert data["error"]["code"] == "APPROVAL_REJECTED"
    assert data["error"]["code"] != "SUBWORKFLOW_FAILED"
    assert _COUNTER["value"] == 1

    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["status"] == "failed"
    assert child["error"]["code"] == "APPROVAL_REJECTED"
    assert "child_after" not in child["node_statuses"]


def test_child_success_is_reused_without_rerunning_the_child(client):
    registered = register_user(client, email="subwf_reuse@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "reuse")

    execution_id, paused = _pause_parent(client, headers, parent_id)
    child_id = paused["pause_state"]["child_execution_id"]

    # Simulate a child that already finished before the parent checkpoint was
    # finalized (e.g. a crash between the two writes).
    from datetime import UTC, datetime

    with get_session() as db:
        row = db.get(Execution, child_id)
        assert row is not None
        row.status = "success"
        row.pause_state = None
        row.error = None
        row.finished_at = datetime.now(UTC)
        row.node_statuses = {"side": "success", "gate": "success", "child_after": "success"}
        row.results = {
            "outputs": {
                "child_after": {
                    "main": [
                        {"value": "ok", "side_effect_count": 1, "reused": True}
                    ]
                }
            },
            "inputs": {},
        }
        db.commit()

    _COUNTER["value"] = 0

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)

    assert data["status"] == "success", data.get("error")
    # The child was not executed again.
    assert _COUNTER["value"] == 0
    sub_items = data["results"]["outputs"]["sub"]["main"]
    assert sub_items[0]["reused"] is True
    assert data["results"]["outputs"]["after"]["main"][0]["parent_done"] is True

    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["status"] == "success"
    assert "reused" in json.dumps(child["results"])


def test_stored_child_failure_propagates_subworkflow_failed(client):
    registered = register_user(client, email="subwf_childfail@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "childfail")

    execution_id, paused = _pause_parent(client, headers, parent_id)
    child_id = paused["pause_state"]["child_execution_id"]

    from datetime import UTC, datetime

    with get_session() as db:
        row = db.get(Execution, child_id)
        assert row is not None
        row.status = "failed"
        row.pause_state = None
        row.finished_at = datetime.now(UTC)
        row.error = {"code": "BOOM", "message": "child exploded"}
        db.commit()

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)

    assert data["status"] == "failed"
    assert data["error"]["code"] == "SUBWORKFLOW_FAILED"
    assert "child exploded" in data["error"]["message"]


def test_running_child_checkpoint_blocks_parent_resume(client):
    registered = register_user(client, email="subwf_busy@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "busy")

    execution_id, paused = _pause_parent(client, headers, parent_id)
    child_id = paused["pause_state"]["child_execution_id"]

    with get_session() as db:
        row = db.get(Execution, child_id)
        assert row is not None
        row.status = "running"
        db.commit()

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)

    assert data["status"] == "failed"
    assert data["error"]["code"] == "SUBWORKFLOW_CHILD_BUSY"
    # No child side effect was duplicated.
    assert _COUNTER["value"] == 1


def test_maintenance_timeout_scan_skips_child_checkpoint(client):
    from datetime import UTC, datetime, timedelta

    from app.maintenance import fail_expired_approvals

    registered = register_user(client, email="subwf_timeout@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "timeout")

    execution_id, paused = _pause_parent(client, headers, parent_id)
    child_id = paused["pause_state"]["child_execution_id"]

    with get_session() as db:
        expired = fail_expired_approvals(
            db, datetime.now(UTC) + timedelta(hours=48)
        )
        assert expired == 1

    with get_session() as db:
        parent = db.get(Execution, execution_id)
        child = db.get(Execution, child_id)
        assert parent is not None and parent.status == "failed"
        assert parent.error["code"] == "APPROVAL_TIMEOUT"
        # The child is a checkpoint: the parent's timeout governs, so the
        # scan must not fail it independently.
        assert child is not None and child.status == "waiting_approval"


# ---------------------------------------------------------------------------
# Event isolation: child node events never overwrite parent statuses
# ---------------------------------------------------------------------------


def test_node_statuses_filters_child_execution_events():
    from app.orchestration.finalizer import node_statuses

    events = [
        {"execution_id": "parent", "node_id": "shared", "status": "success"},
        {"execution_id": "child", "node_id": "shared", "status": "failed"},
        {"execution_id": "child", "node_id": "child_only", "status": "success"},
    ]

    assert node_statuses(events, execution_id="parent") == {"shared": "success"}
    # Without a filter the historical behavior is unchanged.
    assert node_statuses(events) == {"shared": "failed", "child_only": "success"}


# ---------------------------------------------------------------------------
# onceForEach with one effective item (supported scope)
# ---------------------------------------------------------------------------
def test_once_for_each_single_item_creates_checkpoint(client):
    registered = register_user(client, email="subwf_foreach@example.com")
    headers = auth_headers(registered["token"])
    child_id = "wf_sub_child_foreach"
    parent_id = "wf_sub_parent_foreach"
    no_gate = {
        "id": child_id,
        "name": "No gate child",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {"id": "side", "type": SIDE_EFFECT_TYPE, "parameters": {}},
        ],
        "connections": [{"source": "trigger", "target": "side"}],
        "settings": {},
    }
    _create_workflow(client, headers, no_gate)
    _create_workflow(
        client,
        headers,
        _parent_workflow(parent_id, child_id, mode="onceForEach"),
    )

    execution_id = _run(client, headers, parent_id)
    data = _poll(client, execution_id, headers)

    assert data["status"] == "success", data.get("error")
    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["trigger"] == "sub_workflow"
    assert child["status"] == "success"
    assert child["id"].startswith("sub_")
    assert _COUNTER["value"] == 1
    assert data["results"]["outputs"]["sub"]["main"][0]["side_effect_count"] == 1


def _foreach_child_ids(
    execution_id: str, node_id: str, child_workflow_id: str, total: int
) -> list[str]:
    return [
        child_execution_id(execution_id, node_id, "onceForEach", index, child_workflow_id)
        for index in range(total)
    ]


def test_multi_item_once_for_each_stops_at_first_pause_and_resumes_in_order(client):
    registered = register_user(client, email="subwf_multi_seq@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    child_id = "wf_sub_child_multi_seq"
    parent_id = "wf_sub_parent_multi_seq"
    _create_workflow(client, headers, _human_child(child_id, user_id))
    _create_workflow(
        client, headers, _parent_workflow(parent_id, child_id, mode="onceForEach")
    )

    execution_id = _run(
        client,
        headers,
        parent_id,
        data=[{"value": "a"}, {"value": "b"}, {"value": "c"}],
    )
    data = _poll(client, execution_id, headers)

    assert data["status"] == "waiting_approval", data.get("error")
    pause = data["pause_state"]
    assert pause["mode"] == "onceForEach"
    assert pause["item_index"] == 0
    assert pause["item_total"] == 3

    child_ids = _foreach_child_ids(execution_id, "sub", child_id, 3)
    assert pause["child_execution_id"] == child_ids[0]
    child0 = _child_row(child_ids[0])
    assert child0 is not None and child0["status"] == "waiting_approval"
    # Later items must not start before the paused item is approved.
    assert _child_row(child_ids[1]) is None
    assert _child_row(child_ids[2]) is None
    assert _COUNTER["value"] == 1

    # Item 0 completes; item 1 runs and pauses at its own gate.
    data = _approve(client, headers, execution_id)
    assert data["status"] == "waiting_approval", data.get("error")
    assert data["pause_state"]["item_index"] == 1
    assert data["pause_state"]["item_total"] == 3
    assert data["pause_state"]["child_execution_id"] == child_ids[1]
    child0 = _child_row(child_ids[0])
    child1 = _child_row(child_ids[1])
    assert child0 is not None and child0["status"] == "success"
    assert child1 is not None and child1["status"] == "waiting_approval"
    assert _child_row(child_ids[2]) is None
    assert _COUNTER["value"] == 2

    # Item 1 completes; only then does item 2 run.
    data = _approve(client, headers, execution_id)
    assert data["status"] == "waiting_approval", data.get("error")
    assert data["pause_state"]["item_index"] == 2
    assert data["pause_state"]["child_execution_id"] == child_ids[2]
    assert _child_row(child_ids[2]) is not None
    assert _COUNTER["value"] == 3

    data = _approve(client, headers, execution_id)
    assert data["status"] == "success", data.get("error")
    assert _COUNTER["value"] == 3

    sub_items = data["results"]["outputs"]["sub"]["main"]
    assert len(sub_items) == 3
    assert [item["side_effect_count"] for item in sub_items] == [1, 2, 3]
    assert all(item["child_done"] is True for item in sub_items)
    assert [item["value"] for item in sub_items] == ["a", "b", "c"]
    assert [_child_row(cid)["status"] for cid in child_ids] == [
        "success",
        "success",
        "success",
    ]


def test_multi_item_once_for_each_single_approval_completes_remaining_items(client):
    registered = register_user(client, email="subwf_multi_first@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    child_id = "wf_sub_child_multi_first"
    parent_id = "wf_sub_parent_multi_first"
    _create_workflow(
        client, headers, _conditional_human_child(child_id, user_id, gate_on_value="a")
    )
    _create_workflow(
        client, headers, _parent_workflow(parent_id, child_id, mode="onceForEach")
    )

    execution_id = _run(
        client,
        headers,
        parent_id,
        data=[{"value": "a"}, {"value": "b"}, {"value": "c"}],
    )
    data = _poll(client, execution_id, headers)
    assert data["status"] == "waiting_approval", data.get("error")
    assert data["pause_state"]["item_index"] == 0
    child_ids = _foreach_child_ids(execution_id, "sub", child_id, 3)
    assert _child_row(child_ids[1]) is None
    assert _child_row(child_ids[2]) is None
    assert _COUNTER["value"] == 1

    # A single approval resumes item 0 and then runs the remaining items.
    data = _approve(client, headers, execution_id)
    assert data["status"] == "success", data.get("error")
    assert _COUNTER["value"] == 3

    sub_items = data["results"]["outputs"]["sub"]["main"]
    assert len(sub_items) == 3
    assert [item["value"] for item in sub_items] == ["a", "b", "c"]
    assert [item["side_effect_count"] for item in sub_items] == [1, 2, 3]
    assert sub_items[0]["gated"] is True
    assert sub_items[1]["bypassed"] is True
    assert sub_items[2]["bypassed"] is True
    assert [_child_row(cid)["status"] for cid in child_ids] == [
        "success",
        "success",
        "success",
    ]


def test_multi_item_once_for_each_reuses_completed_item_before_second_pause(client):
    registered = register_user(client, email="subwf_multi_second@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    child_id = "wf_sub_child_multi_second"
    parent_id = "wf_sub_parent_multi_second"
    _create_workflow(
        client, headers, _conditional_human_child(child_id, user_id, gate_on_value="b")
    )
    _create_workflow(
        client, headers, _parent_workflow(parent_id, child_id, mode="onceForEach")
    )

    execution_id = _run(
        client,
        headers,
        parent_id,
        data=[{"value": "a"}, {"value": "b"}, {"value": "c"}],
    )
    data = _poll(client, execution_id, headers)
    assert data["status"] == "waiting_approval", data.get("error")
    assert data["pause_state"]["item_index"] == 1
    assert data["pause_state"]["item_total"] == 3

    child_ids = _foreach_child_ids(execution_id, "sub", child_id, 3)
    assert data["pause_state"]["child_execution_id"] == child_ids[1]
    child0 = _child_row(child_ids[0])
    child1 = _child_row(child_ids[1])
    assert child0 is not None and child0["status"] == "success"
    assert child1 is not None and child1["status"] == "waiting_approval"
    assert _child_row(child_ids[2]) is None
    assert _COUNTER["value"] == 2
    assert (
        child0["results"]["outputs"]["after_bypass"]["main"][0]["side_effect_count"]
        == 1
    )

    # Item 0 is reused (not re-executed); item 1 resumes; item 2 then runs.
    data = _approve(client, headers, execution_id)
    assert data["status"] == "success", data.get("error")
    assert _COUNTER["value"] == 3

    sub_items = data["results"]["outputs"]["sub"]["main"]
    assert len(sub_items) == 3
    assert [item["value"] for item in sub_items] == ["a", "b", "c"]
    assert [item["side_effect_count"] for item in sub_items] == [1, 2, 3]
    assert sub_items[0]["bypassed"] is True
    assert sub_items[1]["gated"] is True
    assert sub_items[2]["bypassed"] is True


def test_multi_item_once_for_each_reject_stops_later_items(client):
    registered = register_user(client, email="subwf_multi_reject@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    child_id = "wf_sub_child_multi_reject"
    parent_id = "wf_sub_parent_multi_reject"
    _create_workflow(
        client, headers, _conditional_human_child(child_id, user_id, gate_on_value="b")
    )
    _create_workflow(
        client, headers, _parent_workflow(parent_id, child_id, mode="onceForEach")
    )

    execution_id = _run(
        client,
        headers,
        parent_id,
        data=[{"value": "a"}, {"value": "b"}, {"value": "c"}],
    )
    _poll(client, execution_id, headers)
    assert _COUNTER["value"] == 2

    data = _approve(client, headers, execution_id, approved=False)
    assert data["status"] == "failed"
    assert data["error"]["code"] == "APPROVAL_REJECTED"
    assert _COUNTER["value"] == 2

    child_ids = _foreach_child_ids(execution_id, "sub", child_id, 3)
    assert _child_row(child_ids[0])["status"] == "success"
    rejected = _child_row(child_ids[1])
    assert rejected is not None and rejected["status"] == "failed"
    assert rejected["error"]["code"] == "APPROVAL_REJECTED"
    # The item after the rejected one never started.
    assert _child_row(child_ids[2]) is None
    assert len(_child_rows(execution_id)) == 2


# ---------------------------------------------------------------------------
# Unsupported nested-pause modes fail loudly
# ---------------------------------------------------------------------------


def _defined_approval_child() -> dict[str, Any]:
    return {
        "id": "wf_defined_approval",
        "name": "Defined approval child",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "gate",
                "type": "human_approval",
                "parameters": {"message": "Approve?"},
            },
        ],
        "connections": [{"source": "trigger", "target": "gate"}],
    }


@pytest.mark.asyncio
async def test_define_below_pause_is_rejected():
    with pytest.raises(NodeExecutionError) as exc_info:
        await SubWorkflowNode().run(
            _ctx(),
            SubWorkflowParams(
                source="defineBelow",
                workflow_json=_defined_approval_child(),
            ),
            [{"value": "ok"}],
        )
    assert exc_info.value.code == "SUBWORKFLOW_PAUSE_UNSUPPORTED"


@pytest.mark.asyncio
async def test_background_pause_is_rejected():
    with pytest.raises(NodeExecutionError) as exc_info:
        await SubWorkflowNode().run(
            _ctx(),
            SubWorkflowParams(
                source="defineBelow",
                workflow_json=_defined_approval_child(),
                options={"waitForSubWorkflowCompletion": False},
            ),
            [{"value": "ok"}],
        )
    assert exc_info.value.code == "SUBWORKFLOW_PAUSE_UNSUPPORTED"


@pytest.mark.asyncio
async def test_multi_item_once_for_each_pause_is_rejected():
    with pytest.raises(NodeExecutionError) as exc_info:
        await SubWorkflowNode().run(
            _ctx(),
            SubWorkflowParams(
                source="defineBelow",
                workflow_json=_defined_approval_child(),
                mode="onceForEach",
            ),
            [{"value": "a"}, {"value": "b"}, {"value": "c"}],
        )
    assert exc_info.value.code == "SUBWORKFLOW_PAUSE_UNSUPPORTED"


# ---------------------------------------------------------------------------
# Node-scoped decision guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_ignores_decision_for_another_node():
    ctx = _ctx(node_id="gate")
    await ctx.storage.set(
        "_approval_data", {"approved": True, "approved_by": 9, "node_id": "other"}
    )

    result = await HumanApprovalNode().run(ctx, HumanApprovalParams(), [{"value": "ok"}])

    # The mismatched decision was not consumed: the node pauses instead of
    # approving.
    assert result.metadata.get("waiting_approval") is True
    assert result.output_items == []


def test_agent_resume_state_ignores_decision_for_another_node():
    from app.nodes.ai_agent import AIAgentNode

    ctx = _ctx(node_id="agent")
    state = AIAgentNode()._load_tool_resume_state(
        ctx,
        {
            "pause_type": "tool_approval",
            "approved": True,
            "node_id": "upstream_gate",
        },
    )
    assert state is None


# ---------------------------------------------------------------------------
# Nested agent tool approval
# ---------------------------------------------------------------------------


def test_nested_agent_tool_approval_pauses_and_resumes(client, monkeypatch):
    import app.nodes.ai_agent as agent_module

    registered = register_user(client, email="subwf_tool@example.com")
    headers = auth_headers(registered["token"])

    calls: dict[str, Any] = {"chat": 0, "tools": []}

    async def fake_chat(_cred, messages, **_kwargs):
        calls["chat"] += 1
        if calls["chat"] == 1:
            return {"content": None, "tool_calls": [_tool_call()]}
        return {"content": "Inserted the row.", "tool_calls": []}

    async def fake_execute(_ctx, name, args, **kwargs):
        calls["tools"].append((name, args, kwargs))
        return "1 row inserted"

    def fake_preflight(_ctx, name, args, **_kwargs):
        raise ToolApprovalRequired(name, args, risk_class="write", risk_tier=1)

    monkeypatch.setattr(agent_module, "chat_completion", fake_chat)
    monkeypatch.setattr(agent_module, "execute_tool", fake_execute)
    monkeypatch.setattr(agent_module, "preflight_tool_call", fake_preflight)

    child_id = "wf_sub_child_tool"
    parent_id = "wf_sub_parent_tool"
    _create_workflow(client, headers, _agent_child(child_id))
    _create_workflow(client, headers, _parent_workflow(parent_id, child_id))

    execution_id, paused = _pause_parent(client, headers, parent_id)
    pause = paused["pause_state"]
    assert pause["type"] == "sub_workflow"
    assert pause["node_id"] == "sub"
    assert pause["child_node_id"] == "agent"
    assert pause["child_pause_type"] == "tool_approval"
    assert pause["tool_name"] == "datatable_insert_row"
    assert pause["risk_tier"] == 1
    assert calls["tools"] == []

    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["status"] == "waiting_approval"
    assert child["pause_state"]["type"] == "tool_approval"
    assert child["pause_state"]["node_id"] == "agent"
    assert "state" in child["pause_state"]
    assert "state" not in pause

    root_requests = _approval_rows(execution_id)
    assert len(root_requests) == 1
    assert root_requests[0]["node_id"] == "sub"
    assert root_requests[0]["workflow_id"] == parent_id
    assert _approval_rows(child["id"]) == []

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)

    assert data["status"] == "success", data.get("error")
    assert calls["chat"] == 2
    assert len(calls["tools"]) == 1
    _name, _args, kwargs = calls["tools"][0]
    assert kwargs["approval_granted"] is True
    sub_items = data["results"]["outputs"]["sub"]["main"]
    assert sub_items[0]["agent_answer"] == "Inserted the row."

    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["status"] == "success"

# ---------------------------------------------------------------------------
# Child checkpoint API guards
# ---------------------------------------------------------------------------


def test_child_checkpoint_hidden_from_default_execution_list(client):
    registered = register_user(client, email="subwf_list@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "list")

    execution_id, _paused = _pause_parent(client, headers, parent_id)
    child = _child_snapshot(execution_id)
    assert child is not None

    default_rows = client.get(
        "/api/executions?status=waiting_approval", headers=headers
    ).json()["data"]
    default_ids = {row["id"] for row in default_rows}
    assert execution_id in default_ids
    assert child["id"] not in default_ids

    included_rows = client.get(
        "/api/executions?status=waiting_approval&include_children=true",
        headers=headers,
    ).json()["data"]
    included_ids = {row["id"] for row in included_rows}
    assert child["id"] in included_ids


def test_child_checkpoint_cannot_be_resumed_directly(client):
    registered = register_user(client, email="subwf_childresume@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "childresume")

    execution_id, _paused = _pause_parent(client, headers, parent_id)
    child = _child_snapshot(execution_id)
    assert child is not None

    response = client.post(
        f"/api/executions/{child['id']}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert "parent execution" in response.text.lower()


def test_child_checkpoint_cannot_be_cancelled_directly(client):
    registered = register_user(client, email="subwf_childcancel@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "childcancel")

    execution_id, _paused = _pause_parent(client, headers, parent_id)
    child = _child_snapshot(execution_id)
    assert child is not None

    response = client.post(
        f"/api/executions/{child['id']}/cancel", json={}, headers=headers
    )
    assert response.status_code == 409, response.text
    assert "parent execution" in response.text.lower()


def test_has_running_execution_ignores_child_checkpoint(client):
    from app.api.executions import has_running_execution

    registered = register_user(client, email="subwf_running@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, child_id = _setup_human_child(client, headers, user_id, "running")

    execution_id, _paused = _pause_parent(client, headers, parent_id)
    with get_session() as db:
        assert has_running_execution(db, child_id) is False


def test_cancel_waiting_parent_cancels_child_checkpoint(client):
    registered = register_user(client, email="subwf_cascade@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id, _child_id = _setup_human_child(client, headers, user_id, "cascade")

    execution_id, _paused = _pause_parent(client, headers, parent_id)
    child = _child_snapshot(execution_id)
    assert child is not None

    cancelled = client.post(
        f"/api/executions/{execution_id}/cancel", json={}, headers=headers
    )
    assert cancelled.status_code == 200, cancelled.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "cancelled"

    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["status"] == "cancelled"
    assert child["pause_state"] == {}
    assert child["finished_at"] is not None

# ---------------------------------------------------------------------------
# defineBelow and deeper nesting
# ---------------------------------------------------------------------------


def _parent_define_below(parent_id: str, child_json: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": parent_id,
        "name": "Define-below parent",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sub",
                "type": "sub_workflow",
                "parameters": {
                    "source": "defineBelow",
                    "workflow_json": child_json,
                    "mode": "onceWithAll",
                    "options": {"waitForSubWorkflowCompletion": True},
                    "data": {},
                },
            },
            {
                "id": "after",
                "type": "set_data",
                "parameters": {"fields": {"parent_done": True}},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "sub"},
            {"source": "sub", "target": "after"},
        ],
        "settings": {},
    }


def _child_with_sub(child_id: str, grandchild_id: str) -> dict[str, Any]:
    return {
        "id": child_id,
        "name": "Nested child",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sub",
                "type": "sub_workflow",
                "parameters": {
                    "source": "database",
                    "workflow_selector": "id",
                    "workflow_id": grandchild_id,
                    "mode": "onceWithAll",
                    "options": {"waitForSubWorkflowCompletion": True},
                    "data": {},
                },
            },
            {
                "id": "child_after",
                "type": "set_data",
                "parameters": {"fields": {"child_done": True}},
            },
        ],
        "connections": [
            {"source": "trigger", "target": "sub"},
            {"source": "sub", "target": "child_after"},
        ],
        "settings": {},
    }


def test_define_below_child_pauses_and_resumes_with_parent_fk(client):
    registered = register_user(client, email="subwf_definebelow@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    parent_id = "wf_sub_parent_define"
    child_json = _human_child("wf_inline_child", user_id)
    _create_workflow(client, headers, _parent_define_below(parent_id, child_json))

    execution_id, paused = _pause_parent(client, headers, parent_id)
    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["workflow_id"] == parent_id  # FK points at the real parent workflow
    assert child["results"]["outputs"]  # inline snapshot ran upstream
    assert paused["pause_state"]["type"] == "sub_workflow"
    assert paused["pause_state"]["child_node_id"] == "gate"
    assert _COUNTER["value"] == 1

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success", data.get("error")
    assert _COUNTER["value"] == 1
    assert data["results"]["outputs"]["after"]["main"][0]["parent_done"] is True


def test_two_level_nested_approval_pauses_and_resumes(client):
    registered = register_user(client, email="subwf_twolevel@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    grandchild_id = "wf_sub_grandchild_two"
    child_id = "wf_sub_child_two"
    parent_id = "wf_sub_parent_two"
    _create_workflow(client, headers, _human_child(grandchild_id, user_id))
    _create_workflow(client, headers, _child_with_sub(child_id, grandchild_id))
    _create_workflow(client, headers, _parent_workflow(parent_id, child_id))

    execution_id, paused = _pause_parent(client, headers, parent_id)
    child = _child_snapshot(execution_id)
    assert child is not None
    assert child["workflow_id"] == child_id
    assert child["status"] == "waiting_approval"
    assert child["pause_state"]["type"] == "sub_workflow"

    with get_session() as db:
        grandchild = db.scalar(
            select(Execution).where(
                Execution.parent_execution_id == child["id"],
                Execution.trigger == "sub_workflow",
            )
        )
        assert grandchild is not None
        grandchild_id_actual = grandchild.id
        assert grandchild.workflow_id == grandchild_id
        assert grandchild.status == "waiting_approval"
        assert grandchild.pause_state["node_id"] == "gate"

    root_requests = _approval_rows(execution_id)
    assert len(root_requests) == 1
    assert root_requests[0]["node_id"] == "sub"
    assert root_requests[0]["run_id"] == execution_id

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "success", data.get("error")
    assert _COUNTER["value"] == 1

    with get_session() as db:
        child_row = db.get(Execution, child["id"])
        grandchild_row = db.get(Execution, grandchild_id_actual)
        assert child_row is not None and child_row.status == "success"
        assert grandchild_row is not None and grandchild_row.status == "success"
        assert grandchild_row.pause_state is None


def test_cancel_waiting_parent_cancels_two_level_descendants(client):
    registered = register_user(client, email="subwf_twocancel@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    grandchild_id = "wf_sub_grandchild_cancel"
    child_id = "wf_sub_child_cancel"
    parent_id = "wf_sub_parent_cancel"
    _create_workflow(client, headers, _human_child(grandchild_id, user_id))
    _create_workflow(client, headers, _child_with_sub(child_id, grandchild_id))
    _create_workflow(client, headers, _parent_workflow(parent_id, child_id))

    execution_id, _paused = _pause_parent(client, headers, parent_id)
    child = _child_snapshot(execution_id)
    assert child is not None
    with get_session() as db:
        grandchild = db.scalar(
            select(Execution).where(
                Execution.parent_execution_id == child["id"],
                Execution.trigger == "sub_workflow",
            )
        )
        assert grandchild is not None
        grandchild_id_actual = grandchild.id

    cancelled = client.post(
        f"/api/executions/{execution_id}/cancel", json={}, headers=headers
    )
    assert cancelled.status_code == 200, cancelled.text
    data = _poll(client, execution_id, headers)
    assert data["status"] == "cancelled"

    with get_session() as db:
        child_row = db.get(Execution, child["id"])
        grandchild_row = db.get(Execution, grandchild_id_actual)
        assert child_row is not None and child_row.status == "cancelled"
        assert grandchild_row is not None and grandchild_row.status == "cancelled"
        assert grandchild_row.pause_state is None
