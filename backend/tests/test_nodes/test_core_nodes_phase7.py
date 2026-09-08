"""Core automation nodes (Phase 43): Switch, Filter, Wait, GraphQL."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.engine.errors import NodeCancelledError, NodeExecutionError
from app.engine.node_base import MemoryKVStore, NodeContext, NodeResult



def _ctx(cancelled=False):
    import logging

    ctx = NodeContext(
        execution_id="e", workflow_id="wf", logger=logging.getLogger("t"),
        http_client=None, storage=MemoryKVStore(),
    )
    if cancelled:
        ctx._cancelled = True
    return ctx


# ----------------------------------------------------------------------
# Switch
# ----------------------------------------------------------------------

def test_switch_routes_first_match():
    from app.nodes.switch import SwitchNode, SwitchParams, SwitchRule

    node = SwitchNode()
    params = SwitchParams(rules=[
        SwitchRule(left="$json.type", operator="equals", right="A", output="route_0"),
        SwitchRule(left="$json.type", operator="equals", right="B", output="route_1"),
    ])
    items = [{"type": "B", "i": 1}, {"type": "C", "i": 2}, {"type": "A", "i": 3}]
    result = asyncio.new_event_loop().run_until_complete(node.run(_ctx(), params, items))
    assert result.output_by_handle["route_0"] == [{"type": "A", "i": 3}]
    assert result.output_by_handle["route_1"] == [{"type": "B", "i": 1}]
    assert result.output_by_handle["default"] == [{"type": "C", "i": 2}]


def test_switch_default_when_no_rules():
    from app.nodes.switch import SwitchNode, SwitchParams

    node = SwitchNode()
    result = asyncio.new_event_loop().run_until_complete(
        node.run(_ctx(), SwitchParams(rules=[]), [{"x": 1}])
    )
    assert result.output_by_handle["default"] == [{"x": 1}]


def test_switch_operator_starts_with():
    from app.nodes.switch import SwitchNode, SwitchParams, SwitchRule

    node = SwitchNode()
    params = SwitchParams(rules=[
        SwitchRule(left="$json.name", operator="starts_with", right="alert-", output="route_2"),
    ])
    result = asyncio.new_event_loop().run_until_complete(
        node.run(_ctx(), params, [{"name": "alert-high"}])
    )
    assert result.output_by_handle["route_2"] == [{"name": "alert-high"}]


# ----------------------------------------------------------------------
# Filter
# ----------------------------------------------------------------------

def test_filter_keeps_matching_items_only():
    from app.nodes.filter import FilterNode, FilterParams
    from app.nodes.if_condition import Condition

    node = FilterNode()
    params = FilterParams(condition=Condition(
        left="$json.score", operator="greater_than", right="50",
    ))
    items = [{"score": 10}, {"score": 60}, {"score": 90}, {"score": 5}]
    result = asyncio.new_event_loop().run_until_complete(node.run(_ctx(), params, items))
    got = [i["score"] for i in result.output_items]
    assert got == [60, 90]


def test_filter_all_dropped_returns_empty():
    from app.nodes.filter import FilterNode, FilterParams
    from app.nodes.if_condition import Condition

    node = FilterNode()
    params = FilterParams(condition=Condition(left="$json.x", operator="exists"))
    result = asyncio.new_event_loop().run_until_complete(
        node.run(_ctx(), [], [])
    )
    assert result.output_items == []


# ----------------------------------------------------------------------
# Wait / Delay
# ----------------------------------------------------------------------

def test_wait_delay_sleeps_then_passes_items():
    from app.nodes.wait import WaitNode, WaitParams

    node = WaitNode()
    loop = asyncio.new_event_loop()
    start = loop.time()
    result = loop.run_until_complete(
        node.run(_ctx(), WaitParams(mode="delay", seconds=0.4), [{"passed": True}])
    )
    elapsed = loop.time() - start
    loop.close()
    assert result.output_items == [{"passed": True}]
    assert elapsed >= 0.35


def test_wait_cancel_raises_node_cancelled():
    from app.nodes.wait import WaitNode, WaitParams

    node = WaitNode()
    with pytest.raises(NodeCancelledError):
        asyncio.new_event_loop().run_until_complete(
            node.run(_ctx(cancelled=True), WaitParams(mode="delay", seconds=30), [])
        )


def test_wait_until_past_timestamp_returns_immediately():
    from app.nodes.wait import WaitNode, WaitParams

    node = WaitNode()
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    result = asyncio.new_event_loop().run_until_complete(
        node.run(_ctx(), WaitParams(mode="until", until=past), [{"ok": 1}])
    )
    assert result.output_items == [{"ok": 1}]


def test_wait_invalid_timestamp_rejected_at_validation():
    from app.nodes.wait import WaitParams

    with pytest.raises(ValueError, match="ISO-8601"):
        WaitParams(mode="until", until="not-a-date")


# ----------------------------------------------------------------------
# GraphQL
# ----------------------------------------------------------------------

class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _gql_ctx(fake):
    import logging

    return NodeContext(execution_id="e", workflow_id="w",
                       logger=logging.getLogger("t"), http_client=fake,
                       storage=MemoryKVStore())


def _resp(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "http://gql.test"))


def test_graphql_success_returns_data():
    fake = FakeHTTPClient([
        _resp({"data": {"user": {"id": 1}}}),
    ])
    node = __import__("app.nodes.graphql", fromlist=["GraphQLNode"]).GraphQLNode()
    params = __import__("app.nodes.graphql", fromlist=["GraphQLParams"]).GraphQLParams(
        url="http://gql.test", query="query { user { id } }",
    )
    result = asyncio.new_event_loop().run_until_complete(node.run(_gql_ctx(fake), params, [{}]))
    out = result.output_items[0]
    assert out["data"]["user"]["id"] == 1
    # POST body shape
    m, u, k = fake.calls[0]
    assert k["json"]["query"] == "query { user { id } }"
    assert u == "http://gql.test"


def test_graphql_errors_become_typed_error():
    from app.connectors import ConnectorError
    from app.nodes.graphql import GraphQLNode, GraphQLParams

    fake = FakeHTTPClient([
        _resp({"errors": [{"message": "User not found"}], "data": None}),
    ])
    node = GraphQLNode()
    params = GraphQLParams(url="http://gql.test", query="{ user }")
    with pytest.raises(NodeExecutionError) as ei:
        asyncio.new_event_loop().run_until_complete(node.run(_gql_ctx(fake), params, [{}]))
    assert "User not found" in str(ei.value)


def test_graphql_auth_and_variables_sent():
    from app.nodes.graphql import GraphQLNode, GraphQLParams

    fake = FakeHTTPClient([
        _resp({"data": {"ok": True}}),
    ])
    node = GraphQLNode()
    params = GraphQLParams(
        url="http://gql.test", query="mutation($n:String){create(name:$n)}",
        variables={"n": "ada"}, auth_type="bearer", auth_token="tok9",
    )
    asyncio.new_event_loop().run_until_complete(node.run(_gql_ctx(fake), params, [{}]))
    _, _, k = fake.calls[0]
    assert k["headers"]["Authorization"] == "Bearer tok9"
    assert k["json"]["variables"] == {"n": "ada"}


def test_graphql_http_500_is_retryable():
    from app.engine.errors import NodeExecutionError
    from app.nodes.graphql import GraphQLNode, GraphQLParams

    fake = FakeHTTPClient([
        _resp({"message": "boom"}),  # non-JSON-shaped error over HTTP 500? use status override
    ])
    # craft a 500 response manually
    fake.responses = [
        httpx.Response(500, json={"message": "boom"}, request=httpx.Request("POST", "http://gql.test")),
    ]
    node = GraphQLNode()
    params = GraphQLParams(url="http://gql.test", query="{ x }")
    with pytest.raises(NodeExecutionError) as ei:
        asyncio.new_event_loop().run_until_complete(node.run(_gql_ctx(fake), params, [{}]))
    assert ei.value.retryable is True


# ----------------------------------------------------------------------
# Registration + catalog contract
# ----------------------------------------------------------------------

def test_new_nodes_registered_and_discoverable():
    from app.nodes.registry import NODE_REGISTRY

    for t in ("switch", "filter", "wait", "graphql"):
        assert t in NODE_REGISTRY, f"{t} missing"


