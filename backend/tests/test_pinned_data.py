"""Test data pinning on workflow nodes (Phase 1).

Verifies that when `pinned_data` is set on a node:
1. The node's live execution (HTTP request / code / connector) is bypassed.
2. The pinned mock output is returned immediately as the node's result.
3. Downstream connected nodes receive the pinned data as their input.
"""

from __future__ import annotations

import pytest

from app.engine.executor import execute_workflow
from app.schemas.workflow import Connection, Workflow, WorkflowNode


@pytest.mark.asyncio
async def test_pinned_data_bypasses_live_execution():
    """An HTTP request node with invalid URL would fail, but with pinned_data it succeeds."""
    nodes = [
        WorkflowNode(
            id="node_manual",
            type="manual_trigger",
            parameters={},
        ),
        WorkflowNode(
            id="node_http",
            type="http_request",
            parameters={"url": "http://invalid-domain-that-does-not-exist.local/api", "method": "GET"},
            pinned_data=[{"id": 101, "name": "Alice Pinned", "role": "admin"}],
        ),
        WorkflowNode(
            id="node_code",
            type="code",
            parameters={
                "code": "return [{'greeting': f'Hello {item[\"name\"]}'} for item in items]",
                "language": "python",
            },
        ),
    ]
    connections = [
        Connection(source="node_manual", target="node_http"),
        Connection(source="node_http", target="node_code"),
    ]
    wf = Workflow(id="wf_pinned_test", name="Pinned Test", nodes=nodes, connections=connections)

    res = await execute_workflow(wf, trigger_items=[{}])
    assert res.status == "success"
    assert "node_http" in res.results
    http_out = res.results["node_http"]["main"]
    assert http_out == [{"id": 101, "name": "Alice Pinned", "role": "admin"}]

    # Verify downstream node received the pinned data
    assert "node_code" in res.results
    code_out = res.results["node_code"]["main"]
    assert code_out == [{"greeting": "Hello Alice Pinned"}]

    # Verify trace mentions pinned data
    http_step = next(s for s in res.trace if s["node_id"] == "node_http")
    assert "pinned mock data" in http_step.get("note", "").lower()


@pytest.mark.asyncio
async def test_pinned_data_dict_format():
    """Pinned data formatted as dict with main handle or plain dict."""
    nodes = [
        WorkflowNode(
            id="node_a",
            type="manual_trigger",
            pinned_data={"status": "ok", "count": 42},
        )
    ]
    wf = Workflow(id="wf_pinned_dict", name="Pinned Dict", nodes=nodes, connections=[])
    res = await execute_workflow(wf)
    assert res.status == "success"
    assert res.results["node_a"]["main"] == [{"status": "ok", "count": 42}]
