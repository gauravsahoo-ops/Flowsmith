"""Tests for the Execute Workflow Trigger node."""

import pytest
import httpx
from app.nodes.execute_workflow_trigger import ExecuteWorkflowTriggerNode, ExecuteWorkflowTriggerParams
from app.engine.node_base import NodeContext


def _make_ctx():
    return NodeContext(
        execution_id="test",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


@pytest.mark.asyncio
async def test_execute_workflow_trigger_passes_items():
    node = ExecuteWorkflowTriggerNode()
    ctx = _make_ctx()
    params = ExecuteWorkflowTriggerParams()
    input_items = [{"foo": "bar"}, {"num": 42}]
    result = await node.run(ctx, params, input_items)
    assert result.output_items == input_items


@pytest.mark.asyncio
async def test_execute_workflow_trigger_empty_items():
    node = ExecuteWorkflowTriggerNode()
    ctx = _make_ctx()
    params = ExecuteWorkflowTriggerParams()
    result = await node.run(ctx, params, [])
    assert result.output_items == [{}]
