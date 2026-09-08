"""Manual trigger node tests."""

from __future__ import annotations

import logging

import httpx

from app.engine.node_base import NodeContext
from app.nodes.manual_trigger import ManualTriggerNode, ManualTriggerParams


async def _run(items: list[dict]):
    node = ManualTriggerNode()
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
    )
    return await node.run(ctx, ManualTriggerParams(), items)


async def test_passes_items_through():
    result = await _run([{"a": 1}])
    assert result.output_items == [{"a": 1}]


async def test_empty_input_creates_single_item():
    result = await _run([])
    assert result.output_items == [{"success": True}]
