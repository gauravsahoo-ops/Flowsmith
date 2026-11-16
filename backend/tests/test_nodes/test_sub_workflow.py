"""Tests for the Sub-workflow node."""

import pytest
import httpx
from app.nodes.sub_workflow import SubWorkflowNode, SubWorkflowParams
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext


def _make_ctx():
    return NodeContext(
        execution_id="test",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


@pytest.mark.asyncio
async def test_sub_workflow_not_found():
    """Fails with a typed error when workflow not found (Phase 8: a
    misconfigured sub-workflow is never reported as success)."""
    node = SubWorkflowNode()
    ctx = _make_ctx()
    params = SubWorkflowParams(workflow_id="nonexistent")
    items = [{"data": "test"}]
    with pytest.raises(NodeExecutionError) as excinfo:
        await node.run(ctx, params, items)
    assert excinfo.value.code == "SUBWORKFLOW_NOT_FOUND"


@pytest.mark.asyncio
async def test_sub_workflow_pause_is_not_reported_as_failure(monkeypatch):
    """A nested approval pause fails with a dedicated, actionable code."""
    from app.engine.executor import ExecutionResult

    async def fake_execute(*_args, **_kwargs):
        return ExecutionResult(
            status="waiting_approval",
            paused=True,
            paused_node_id="gate",
        )

    import app.engine.executor as executor_module

    monkeypatch.setattr(executor_module, "execute_workflow", fake_execute)

    node = SubWorkflowNode()
    ctx = _make_ctx()
    params = SubWorkflowParams(
        source="defineBelow",
        workflow_json={"id": "child", "nodes": [], "connections": []},
    )
    with pytest.raises(NodeExecutionError) as excinfo:
        await node.run(ctx, params, [{"data": "test"}])
    assert excinfo.value.code == "SUBWORKFLOW_PAUSE_UNSUPPORTED"


def test_sub_workflow_params():
    """Test parameter schema."""
    params = SubWorkflowParams(workflow_id="wf123")
    assert params.workflow_id == "wf123"
    assert params.data == {}
