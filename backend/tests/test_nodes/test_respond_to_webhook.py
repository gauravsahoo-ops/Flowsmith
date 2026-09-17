"""Tests for the Respond to Webhook node."""

import pytest
import httpx
from app.nodes.respond_to_webhook import RespondToWebhookNode, RespondToWebhookParams
from app.engine.node_base import NodeContext


def _make_ctx():
    return NodeContext(
        execution_id="test",
        workflow_id="wf",
        logger=None,
        http_client=httpx.AsyncClient(),
    )


@pytest.mark.asyncio
async def test_respond_input_mode_passes_items_as_body():
    node = RespondToWebhookNode()
    params = RespondToWebhookParams(status_code=201, respond_with="input")
    result = await node.run(_make_ctx(), params, [{"a": 1}, {"b": 2}])
    assert result.output_items == [{"status_code": 201, "body": [{"a": 1}, {"b": 2}]}]


@pytest.mark.asyncio
async def test_respond_first_mode():
    node = RespondToWebhookNode()
    params = RespondToWebhookParams(respond_with="first")
    result = await node.run(_make_ctx(), params, [{"x": 9}])
    assert result.output_items == [{"status_code": 200, "body": {"x": 9}}]


@pytest.mark.asyncio
async def test_respond_json_mode_parses_static_body():
    node = RespondToWebhookNode()
    params = RespondToWebhookParams(status_code=202, respond_with="json", response_body='{"ok": true}')
    result = await node.run(_make_ctx(), params, [{"ignored": 1}])
    assert result.output_items == [{"status_code": 202, "body": {"ok": True}}]


@pytest.mark.asyncio
async def test_respond_json_mode_invalid_json_wraps():
    node = RespondToWebhookNode()
    params = RespondToWebhookParams(respond_with="json", response_body="not-json{{{")
    result = await node.run(_make_ctx(), params, [])
    assert result.output_items[0]["body"] == {"data": "not-json{{{"}


def test_respond_registered():
    from app.nodes.registry import get

    assert get("respond_to_webhook") is RespondToWebhookNode
