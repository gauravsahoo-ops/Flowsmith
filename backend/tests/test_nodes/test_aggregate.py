"""Tests for the Aggregate node."""

import pytest
import httpx
from app.nodes.aggregate import AggregateNode, AggregateParams
from app.engine.node_base import NodeContext


def _make_ctx():
    return NodeContext(
        execution_id="test",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


@pytest.mark.asyncio
async def test_aggregate_collects_items():
    node = AggregateNode()
    ctx = _make_ctx()
    params = AggregateParams()
    items = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    result = await node.run(ctx, params, items)
    assert len(result.output_items) == 1
    assert "items" in result.output_items[0]
    assert len(result.output_items[0]["items"]) == 3


@pytest.mark.asyncio
async def test_aggregate_custom_field():
    node = AggregateNode()
    ctx = _make_ctx()
    params = AggregateParams(field="results")
    items = [{"value": 1}, {"value": 2}]
    result = await node.run(ctx, params, items)
    assert "results" in result.output_items[0]
    assert len(result.output_items[0]["results"]) == 2


@pytest.mark.asyncio
async def test_aggregate_empty():
    node = AggregateNode()
    ctx = _make_ctx()
    params = AggregateParams()
    result = await node.run(ctx, params, [])
    assert result.output_items == [{"items": []}]
