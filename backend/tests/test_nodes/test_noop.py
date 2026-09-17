"""Tests for the NoOp node."""

import pytest
import httpx
from app.nodes.noop import NoOpNode, NoOpParams
from app.engine.node_base import NodeContext


def _make_ctx():
    return NodeContext(
        execution_id="test",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


@pytest.mark.asyncio
async def test_noop_passes_items_through():
    node = NoOpNode()
    items = [{"a": 1}, {"b": 2}]
    result = await node.run(_make_ctx(), NoOpParams(), items)
    assert result.output_items == [{"a": 1}, {"b": 2}]


@pytest.mark.asyncio
async def test_noop_empty_input():
    node = NoOpNode()
    result = await node.run(_make_ctx(), NoOpParams(), [])
    assert result.output_items == []


def test_noop_registered():
    from app.nodes.registry import get

    assert get("noop") is NoOpNode
