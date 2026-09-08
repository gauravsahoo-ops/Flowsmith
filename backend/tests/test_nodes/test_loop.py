"""Tests for the Loop / ForEach node."""

import pytest
import httpx
from app.nodes.loop import LoopNode, LoopParams, _resolve_field
from app.engine.node_base import NodeContext


def _make_ctx():
    return NodeContext(
        execution_id="test",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


@pytest.mark.asyncio
async def test_loop_expands_list_items():
    """When field points to a list, expand it."""
    node = LoopNode()
    ctx = _make_ctx()
    params = LoopParams(field="value")
    items = [{"value": [1, 2, 3]}]
    result = await node.run(ctx, params, items)
    # Each element becomes a separate item
    assert len(result.output_items) == 3
    assert result.output_items[0] == {"value": 1}
    assert result.output_items[1] == {"value": 2}
    assert result.output_items[2] == {"value": 3}


@pytest.mark.asyncio
async def test_loop_with_field_path():
    """Expand a nested list via field path."""
    node = LoopNode()
    ctx = _make_ctx()
    params = LoopParams(field="data.list")
    items = [{"data": {"list": ["a", "b", "c"]}}]
    result = await node.run(ctx, params, items)
    assert len(result.output_items) == 3
    assert result.output_items[0] == {"value": "a"}


@pytest.mark.asyncio
async def test_loop_batch_size():
    """Limit output items to batch_size."""
    node = LoopNode()
    ctx = _make_ctx()
    params = LoopParams(field="data", batch_size=2)
    items = [{"data": [1, 2, 3, 4, 5]}]
    result = await node.run(ctx, params, items)
    assert len(result.output_items) == 2


@pytest.mark.asyncio
async def test_loop_no_input():
    """Empty input returns placeholder."""
    node = LoopNode()
    ctx = _make_ctx()
    params = LoopParams()
    result = await node.run(ctx, params, [])
    assert result.output_items == [{}]


@pytest.mark.asyncio
async def test_loop_dict_passthrough():
    """When no field specified and item is a dict, pass through."""
    node = LoopNode()
    ctx = _make_ctx()
    params = LoopParams()
    items = [{"name": "a", "data": [1, 2]}]
    result = await node.run(ctx, params, items)
    # The dict is passed through as-is (not expanded)
    assert len(result.output_items) == 1
    assert result.output_items[0] == {"name": "a", "data": [1, 2]}


@pytest.mark.asyncio
async def test_loop_field_not_list():
    """When field points to a non-list value, wrap in dict."""
    node = LoopNode()
    ctx = _make_ctx()
    params = LoopParams(field="name")
    items = [{"name": "hello"}]
    result = await node.run(ctx, params, items)
    assert result.output_items == [{"value": "hello"}]


def test_resolve_field():
    assert _resolve_field({"a": {"b": [1, 2]}}, "a.b") == [1, 2]
    assert _resolve_field({"a": 1}, "a") == 1
    assert _resolve_field({"a": 1}, "b") is None
    assert _resolve_field({}, "x") is None
