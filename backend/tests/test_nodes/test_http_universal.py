"""Universal HTTP node features (Phase 6): path/query params, form/raw
bodies, auth schemes, response limits, Link-header pagination."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.engine.node_base import NodeContext, NodeResult
from app.engine.node_base import MemoryKVStore, NodeContext
from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams


class FakeHTTPClient:
    """Records requests; scripted responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        pass

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _json(status, payload, headers=None, url="http://fake"):
    return httpx.Response(status, json=payload, headers=headers or {}, request=httpx.Request("GET", url))


def _ctx(client):
    from app.engine.node_base import MemoryKVStore, NodeContext
    import logging

    return NodeContext(
        execution_id="e", workflow_id="wf", logger=logging.getLogger("t"),
        http_client=client, storage=MemoryKVStore(),
    )


def _node():
    return HTTPRequestNode()


# ----------------------------------------------------------------------

def test_path_params_substitution_and_query():
    fake = FakeHTTPClient([_json(200, {"ok": True})])
    ctx = _ctx(fake)
    params = HTTPRequestParams(
        method="GET", url="https://api.test/users/{userId}/posts/{postId}",
        path_params={"userId": "u1", "postId": "42"},
        query={"limit": 5, "sort": "asc"},
    )
    asyncio_run(_node().run(ctx, params, [{}]))
    m, url, k = fake.calls[0]
    assert url == "https://api.test/users/u1/posts/42"
    assert k["params"] == {"limit": 5, "sort": "asc"}


def test_form_encoding_sets_content_type():
    fake = FakeHTTPClient([
        _json(200, {"ok": True}),
    ])
    ctx = _ctx(fake)
    params = HTTPRequestParams(
        method="POST", url="https://api.test/form",
        body={"a": "1", "b": "2"}, body_format="form",
    )
    asyncio_run(_node().run(ctx, params, [{}]))
    _, _, k = fake.calls[0]
    assert k["data"] == "a=1&b=2"
    assert k["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_raw_body_passthrough():
    fake = FakeHTTPClient([_json(200, {"ok": True})])
    ctx = _ctx(fake)
    params = HTTPRequestParams(
        method="POST", url="https://api.test/raw",
        body="<xml>hello</xml>", body_format="raw",
        headers={"Content-Type": "application/xml"},
    )
    asyncio_run(_node().run(ctx, params, [{}]))
    _, _, k = fake.calls[0]
    assert k["data"] == "<xml>hello</xml>"
    assert k["json"] is None


def test_bearer_auth_header():
    fake = FakeHTTPClient([_json(200, {})])
    ctx = _ctx(fake)
    params = HTTPRequestParams(method="GET", url="https://x.test/", auth_type="bearer", auth_token="tok123")
    asyncio_run(_node().run(ctx, params, [{}]))
    assert fake.calls[0][2]["headers"]["Authorization"] == "Bearer tok123"


def test_basic_auth_header_encodes_credentials():
    fake = FakeHTTPClient([_json(200, {})])
    ctx = _ctx(fake)
    params = HTTPRequestParams(
        method="GET", url="https://x.test/",
        auth_type="basic", auth_username="u", auth_password="p",
    )
    asyncio_run(_node().run(ctx, params, [{}]))
    expected = "Basic " + __import__("base64").b64encode(b"u:p").decode()
    assert fake.calls[0][2]["headers"]["Authorization"] == expected


def test_api_key_in_query_vs_header():
    fake = FakeHTTPClient([_json(200, {}), _json(200, {})])
    ctx = _ctx(fake)
    n = _node()
    asyncio_run(n.run(ctx, HTTPRequestParams(
        method="GET", url="https://x.test/", auth_type="api_key",
        api_key_name="key", auth_token="SECRETQ", api_key_in="query"), [{}]))
    assert fake.calls[0][2]["params"]["key"] == "SECRETQ"

    asyncio_run(n.run(ctx, HTTPRequestParams(
        method="GET", url="https://x.test/", auth_type="api_key",
        api_key_name="X-Key", auth_token="SECRETH", api_key_in="header"), [{}]))
    assert fake.calls[1][2]["headers"]["X-Key"] == "SECRETH"


def test_missing_auth_material_rejected_before_network():
    from app.engine.errors import NodeExecutionError

    fake = FakeHTTPClient([])
    ctx = _ctx(fake)
    with pytest.raises(NodeExecutionError) as ei:
        asyncio_run(_node().run(ctx, HTTPRequestParams(
            method="GET", url="https://x.test/", auth_type="bearer"), [{}]))
    assert "requires auth_token" in str(ei.value)
    assert fake.calls == []  # no network attempt


def test_response_limit_forwarded_to_client():
    captured = {}

    class Client:
        async def request(self, method, url, **kwargs):
            captured.update(kwargs)
            assert kwargs["max_response_bytes"] == 1024
            return _json(200, {"ok": True})

    from app.engine.node_base import MemoryKVStore, NodeContext
    import logging

    ctx = NodeContext(execution_id="e", workflow_id="w", logger=logging.getLogger("t"),
                      http_client=Client(), storage=MemoryKVStore())
    params = HTTPRequestParams(method="GET", url="https://x.test/", max_response_bytes=1024)
    asyncio_run(_node().run(ctx, params, [{}]))


def _resp_with_link(next_url: str | None, payload, url: str = "http://fake/page1"):
    headers = {}
    if next_url:
        link = "<" + next_url + '>; rel="next"'
        headers["Link"] = link
    return httpx.Response(200, json=payload, headers=headers, request=httpx.Request("GET", url))


def test_link_header_pagination_merges_pages():
    fake = FakeHTTPClient([
        _resp_with_link("http://fake/page2", [{"i": 1}, {"i": 2}], url="http://fake/page1"),
        _resp_with_link(None, [{"i": 3}], url="http://fake/page2"),
    ])
    ctx = _ctx(fake)
    params = HTTPRequestParams(
        method="GET", url="http://fake/page1",
        pagination_mode="link_header", max_pages=10,
    )
    result = asyncio_run(_node().run(ctx, params, [{}]))
    out = result.output_items[0]
    assert out["pages"] == 2
    assert out["items"] == [{"i": 1}, {"i": 2}, {"i": 3}]


def test_pagination_disabled_by_default_single_response_shape():
    fake = FakeHTTPClient([
        _resp_with_link("http://fake/page2", [{"i": 1}]),
    ])
    ctx = _ctx(fake)
    params = HTTPRequestParams(method="GET", url="http://fake/page1")
    result = asyncio_run(_node().run(ctx, params, [{}]))
    out = result.output_items[0]
    assert out["status"] == 200 and "pages" not in out


def asyncio_run(coro):
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
