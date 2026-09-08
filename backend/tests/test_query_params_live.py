import asyncio
import logging
import httpx
import pytest
import respx
from app.engine.node_base import MemoryKVStore, NodeContext
from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams

def make_ctx(client: httpx.AsyncClient) -> NodeContext:
    return NodeContext(
        execution_id="test_exec",
        workflow_id="test_wf",
        node_id="http_1",
        logger=logging.getLogger("test"),
        http_client=client,
        storage=MemoryKVStore(),
        emit_event=lambda *a, **k: None,
        credentials={},
        env_vars={},
        user_id=1,
    )

@pytest.mark.asyncio
async def test_fields_mode_query_params():
    node = HTTPRequestNode()
    async with httpx.AsyncClient() as client:
        ctx = make_ctx(client)
        with respx.mock(base_url="https://api.example.com") as respx_mock:
            route = respx_mock.get("/users").respond(json={"status": "ok"})
            params = node.build_params({
                "method": "GET",
                "url": "https://api.example.com/users",
                "sendQuery": True,
                "queryMode": "fields",
                "queryParameters": [
                    {"name": "updated_after", "value": "2026-09-01"},
                    {"name": "limit", "value": "50"}
                ]
            })
            result = await node.run(ctx, params, [{}])
            assert len(result.output_items) == 1
            assert result.output_items[0]["body"] == {"status": "ok"}
            assert route.called
            last_req = route.calls.last.request
            assert "updated_after=2026-09-01" in str(last_req.url)
            assert "limit=50" in str(last_req.url)

@pytest.mark.asyncio
async def test_json_mode_query_params():
    node = HTTPRequestNode()
    async with httpx.AsyncClient() as client:
        ctx = make_ctx(client)
        with respx.mock(base_url="https://api.example.com") as respx_mock:
            route = respx_mock.get("/search").respond(json={"results": [1, 2, 3]})
            params = node.build_params({
                "method": "GET",
                "url": "https://api.example.com/search",
                "sendQuery": True,
                "queryMode": "json",
                "queryJson": '{"query": "antigravity", "page": "2"}'
            })
            result = await node.run(ctx, params, [{}])
            assert len(result.output_items) == 1
            assert result.output_items[0]["body"] == {"results": [1, 2, 3]}
            assert route.called
            last_req = route.calls.last.request
            assert "query=antigravity" in str(last_req.url)
            assert "page=2" in str(last_req.url)

@pytest.mark.asyncio
async def test_expression_resolution_in_query_params():
    node = HTTPRequestNode()
    async with httpx.AsyncClient() as client:
        ctx = make_ctx(client)
        with respx.mock(base_url="https://api.example.com") as respx_mock:
            route = respx_mock.get("/filter").respond(json={"filtered": True})
            params = node.build_params({
                "method": "GET",
                "url": "https://api.example.com/filter",
                "sendQuery": True,
                "queryMode": "fields",
                "queryParameters": [
                    {"name": "user_id", "value": "{{ $json.id }}"}
                ]
            })
            input_items = [{"id": 12345}]
            result = await node.run(ctx, params, input_items)
            assert route.called
            last_req = route.calls.last.request
            assert "user_id=12345" in str(last_req.url)

@pytest.mark.asyncio
async def test_expression_resolution_in_query_json_mode():
    node = HTTPRequestNode()
    async with httpx.AsyncClient() as client:
        ctx = make_ctx(client)
        with respx.mock(base_url="https://api.example.com") as respx_mock:
            route = respx_mock.get("/api/v2").respond(json={"success": True})
            params = node.build_params({
                "method": "GET",
                "url": "https://api.example.com/api/v2",
                "sendQuery": True,
                "queryMode": "json",
                "queryJson": '{"updated_after": "{{ $json.timestamp }}", "status": "active"}'
            })
            input_items = [{"timestamp": "2026-09-04T22:00:00Z"}]
            result = await node.run(ctx, params, input_items)
            assert route.called
            last_req = route.calls.last.request
            assert "updated_after=2026-09-04T22%3A00%3A00Z" in str(last_req.url)
            assert "status=active" in str(last_req.url)

@pytest.mark.asyncio
async def test_send_query_toggle_off_omits_params():
    node = HTTPRequestNode()
    async with httpx.AsyncClient() as client:
        ctx = make_ctx(client)
        with respx.mock(base_url="https://api.example.com") as respx_mock:
            route = respx_mock.get("/items").respond(json=[])
            params = node.build_params({
                "method": "GET",
                "url": "https://api.example.com/items",
                "sendQuery": False,
                "query": {"filter": "hidden"}
            })
            result = await node.run(ctx, params, [{}])
            assert route.called
            last_req = route.calls.last.request
            assert "?" not in str(last_req.url)
