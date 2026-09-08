"""Set / Edit Data node tests."""

from __future__ import annotations

import logging

import httpx

from app.engine.node_base import NodeContext
from app.nodes.set_data import SetDataNode, SetDataParams


async def _run(params: dict, items: list[dict]):
    node = SetDataNode()
    p = SetDataParams(**params)
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
    )
    return await node.run(ctx, p, items)


async def test_merge_mode():
    result = await _run({"fields": {"b": 2}}, [{"a": 1}])
    assert result.output_items == [{"a": 1, "b": 2}]


async def test_replace_mode():
    result = await _run({"mode": "replace", "fields": {"b": 2}}, [{"a": 1}, {"a": 3}])
    assert result.output_items == [{"b": 2}, {"b": 2}]


async def test_no_input_creates_single_item():
    result = await _run({"fields": {"a": 1}}, [])
    assert result.output_items == [{"a": 1}]


async def test_many_items():
    result = await _run({"fields": {"tag": "x"}}, [{"n": 1}, {"n": 2}, {"n": 3}])
    items = result.output_items
    assert items is not None
    assert len(items) == 3
    assert all(i["tag"] == "x" for i in items)
