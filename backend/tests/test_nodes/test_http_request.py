"""HTTP Request node tests (spec 51.3: success, failure, timeout)."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
import respx

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams


async def _make_ctx(client: httpx.AsyncClient) -> NodeContext:
    return NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=client,
    )


async def test_successful_get(respx_mock, http_client):
    respx_mock.get("https://api.example.com/data").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    node = HTTPRequestNode()
    params = HTTPRequestParams(method="GET", url="https://api.example.com/data")
    result = await node.run(await _make_ctx(http_client), params, [{}])

    assert result.output_items is not None
    assert result.output_items[0]["status"] == 200
    assert result.output_items[0]["ok"] is True
    assert result.output_items[0]["headers"]["content-type"] == "application/json"


async def test_post_sends_body(respx_mock, http_client):
    route = respx_mock.post("https://api.example.com/submit").mock(
        return_value=httpx.Response(201, json={"id": 42})
    )
    node = HTTPRequestNode()
    params = HTTPRequestParams(method="POST", url="https://api.example.com/submit", body={"name": "x"})
    result = await node.run(await _make_ctx(http_client), params, [{}])

    assert result.output_items is not None
    assert result.output_items[0]["status"] == 201
    assert json.loads(route.calls.last.request.content) == {"name": "x"}


async def test_body_none_sentinel_sends_no_payload(respx_mock, http_client):
    route = respx_mock.get("https://api.example.com/none").mock(
        return_value=httpx.Response(200, json={})
    )
    node = HTTPRequestNode()
    params = HTTPRequestParams(method="GET", url="https://api.example.com/none", body="none")
    result = await node.run(await _make_ctx(http_client), params, [{}])

    assert result.output_items is not None
    assert result.output_items[0]["status"] == 200
    assert route.calls.last.request.content == b""
    assert route.calls.last.request.headers.get("content-length") is None


async def test_timeout_raises_typed_error(respx_mock, http_client):
    respx_mock.get("https://api.example.com/slow").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    node = HTTPRequestNode()
    params = HTTPRequestParams(method="GET", url="https://api.example.com/slow", timeout_seconds=1.0)
    with pytest.raises(NodeExecutionError) as exc:
        await node.run(await _make_ctx(http_client), params, [{}])
    assert exc.value.code == "HTTP_TIMEOUT"
    assert exc.value.retryable is True


async def test_connection_error_raises_typed_error(respx_mock, http_client):
    respx_mock.get("https://api.example.com/down").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    node = HTTPRequestNode()
    params = HTTPRequestParams(method="GET", url="https://api.example.com/down")
    with pytest.raises(NodeExecutionError) as exc:
        await node.run(await _make_ctx(http_client), params, [{}])
    assert exc.value.code == "HTTP_REQUEST_FAILED"
    assert exc.value.retryable is True


async def test_invalid_url_rejected_by_schema():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HTTPRequestParams(method="GET", url="")


async def test_auto_refresh_on_401_invalid_session_id(respx_mock, http_client, monkeypatch):
    """When a 401 INVALID_SESSION_ID occurs, auto-refresh the token and retry seamlessly."""
    route = respx_mock.get("https://orgfarm.my.salesforce.com/services/data/v59.0/query").mock(
        side_effect=[
            httpx.Response(
                401,
                json=[{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}],
            ),
            httpx.Response(
                200,
                json={"totalSize": 1, "done": True, "records": [{"Id": "001xx000003DHP0AAO"}]},
            ),
        ]
    )

    from app.providers.salesforce import SalesforceProviderClient

    async def _fake_auth(self, creds, force: bool = False, **kwargs):
        return "fresh_sf_token_123"

    monkeypatch.setattr(
        SalesforceProviderClient,
        "authenticate",
        _fake_auth,
    )

    ctx = await _make_ctx(http_client)
    ctx.credentials = {
        "salesforce": {
            "access_token": "expired_old_token",
            "refresh_token": "valid_refresh_token",
            "instance_url": "https://orgfarm.my.salesforce.com",
            "oauth": True,
        }
    }

    node = HTTPRequestNode()
    params = HTTPRequestParams(
        method="GET",
        url="https://orgfarm.my.salesforce.com/services/data/v59.0/query",
        headers={"Authorization": "Bearer expired_old_token"},
    )
    result = await node.run(ctx, params, [{}])

    assert result.output_items is not None
    assert result.output_items[0]["status"] == 200
    assert result.output_items[0]["body"]["records"][0]["Id"] == "001xx000003DHP0AAO"
    assert route.call_count == 2
    # Verify the second call used the newly refreshed token
    assert route.calls.last.request.headers["authorization"] == "Bearer fresh_sf_token_123"

