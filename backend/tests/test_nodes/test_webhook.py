"""Webhook trigger node tests (spec 51.3)."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.engine.node_base import NodeContext
from app.nodes.webhook import WebhookTriggerNode, WebhookTriggerParams


async def _run(params: dict, items: list[Any] | None = None):
    node = WebhookTriggerNode()
    p = WebhookTriggerParams.model_validate(params)
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
    )
    return await node.run(ctx, p, items or [])


# --- valid input -----------------------------------------------------------

async def test_raw_dict_payload_is_wrapped():
    result = await _run({"path": "incoming"}, [{"subject": "hello"}])
    assert result.output_items == [
        {"success": True, "body": {"subject": "hello"}, "headers": {}, "query": {}, "params": {}}
    ]


async def test_list_payload_expands_to_items():
    result = await _run({"path": "incoming"}, [[1, 2]])
    assert result.output_items == [
        {"success": True, "body": 1, "headers": {}, "query": {}, "params": {}},
        {"success": True, "body": 2, "headers": {}, "query": {}, "params": {}},
    ]


async def test_pre_shaped_item_passes_through():
    shaped = {"body": {"a": 1}, "headers": {"x": "y"}, "query": {"q": "1"}, "params": {}}
    result = await _run({"path": "incoming"}, [shaped])
    assert result.output_items == [{"success": True, **shaped}]


async def test_empty_input_creates_empty_item():
    result = await _run({"path": "incoming"})
    assert result.output_items == [{"success": True, "body": {}, "headers": {}, "query": {}, "params": {}}]


# --- invalid input -----------------------------------------------------------

async def test_empty_path_rejected():
    with pytest.raises(ValidationError):
        WebhookTriggerParams.model_validate({"path": ""})


async def test_path_with_invalid_chars_rejected():
    with pytest.raises(ValidationError):
        WebhookTriggerParams.model_validate({"path": "incoming/email"})


async def test_http_verbs_accepted():
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        p = WebhookTriggerParams.model_validate({"path": "x", "method": method})
        assert p.method == method