"""Router / SOAP / String Tools node tests (Phase 7 gaps)."""

from __future__ import annotations

import logging

import httpx
import pytest

from app.engine.node_base import NodeContext
from app.nodes.router import RouterNode, RouterParams
from app.nodes.soap_request import SoapRequestNode, SoapRequestParams
from app.nodes.string_tools import StringToolsNode, StringToolsParams


def _ctx() -> NodeContext:
    return NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
    )


async def test_router_first_match():
    node = RouterNode()
    params = RouterParams.model_validate({"strategy": "first_match", "field": "status", "routes": ["active", "archived"]})
    res = await node.run(_ctx(), params, [{"status": "user active now"}, {"status": "archived item"}, {"status": "other"}])
    assert len(res.output_by_handle["route_0"]) == 1
    assert len(res.output_by_handle["route_1"]) == 1
    assert len(res.output_by_handle["default"]) == 1


async def test_router_all_matches_fans_out():
    node = RouterNode()
    params = RouterParams.model_validate({"strategy": "all_matches", "field": "tags", "routes": ["a", "b"]})
    res = await node.run(_ctx(), params, [{"tags": "a and b"}])
    assert len(res.output_by_handle["route_0"]) == 1
    assert len(res.output_by_handle["route_1"]) == 1


async def test_router_round_robin_distributes():
    node = RouterNode()
    params = RouterParams.model_validate({"strategy": "round_robin", "routes": ["x", "y"]})
    res = await node.run(_ctx(), params, [{"i": 1}, {"i": 2}, {"i": 3}])
    assert len(res.output_by_handle["route_0"]) == 2
    assert len(res.output_by_handle["route_1"]) == 1


async def test_soap_builds_envelope_and_parses(monkeypatch):
    node = SoapRequestNode()
    captured: dict = {}

    class FakeResp:
        status_code = 200
        text = '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><Result><ok>1</ok></Result></soap:Body></soap:Envelope>'

    class FakeClient:
        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResp()

    ctx = _ctx()
    ctx.http_client = FakeClient()  # type: ignore[assignment]
    params = SoapRequestParams.model_validate({"url": "https://example.com/soap", "action": "Ping", "body": {"a": "1"}})
    res = await node.run(ctx, params, [{}])
    assert captured["url"] == "https://example.com/soap"
    assert res.output_items[0]["status_code"] == 200
    assert res.output_items[0]["soap_fault"] is False


async def test_soap_requires_url():
    from app.engine.errors import NodeExecutionError

    node = SoapRequestNode()
    with pytest.raises(NodeExecutionError):
        await node.run(_ctx(), SoapRequestParams.model_validate({"url": ""}), [{}])


@pytest.mark.parametrize("op,value,kwargs,expected", [
    ("upper", "hi", {}, "HI"),
    ("slug", "Hello World!", {}, "hello-world"),
    ("slice", "abcdef", {"start": 1, "end": 3}, "bc"),
    ("replace", "aaa", {"pattern": "a", "replacement": "b"}, "bbb"),
    ("split", "a,b,c", {"separator": ","}, ["a", "b", "c"]),
    ("length", "abcd", {}, 4),
    ("regex_extract", "order 42", {"pattern": r"(\d+)"}, "42"),
    ("regex_match", "hello", {"pattern": r"^h"}, True),
    ("to_number", "42", {}, 42),
    ("concat", "foo", {"extra": "bar"}, "foobar"),
])
async def test_string_tools_ops(op, value, kwargs, expected):
    node = StringToolsNode()
    params = StringToolsParams.model_validate({"operation": op, "source": "text", **kwargs})
    res = await node.run(_ctx(), params, [{"text": value}])
    assert res.output_items[0]["text"] == expected
