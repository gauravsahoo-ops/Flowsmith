"""Automated tests for user feedback features:
- Detailed 401 & HTTP error logging (responseBody, url, method, headers preserved)
- Upstream token auto-fallback when bearer token is unconfigured
- Lifecycle method hooks (on_init_headers, on_success_expression, on_error_action)
- SetVariableNode (setting $env in context and workspace)
"""

import pytest
import httpx
import respx
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.http_request import HTTPRequestNode, HTTPRequestParams
from app.nodes.set_variable import SetVariableNode, SetVariableParams


class MockStorage:
    async def get(self, key):
        return None
    async def set(self, key, val):
        pass


import logging

@pytest.fixture
def node_context():
    ctx = NodeContext(
        workflow_id="wf_test",
        workspace_id="ws_test",
        node_id="http_1",
        execution_id="exec_1",
        logger=logging.getLogger("test"),
        storage=MockStorage(),
        http_client=httpx.AsyncClient(),
        env_vars={"API_HOST": "api.test.com"},
    )
    ctx.expression_context = {"$env": {"API_HOST": "api.test.com"}}
    return ctx


@pytest.mark.asyncio
@respx.mock
async def test_http_401_preserves_detailed_error_and_body(node_context):
    """Problem 1: HTTP 401 includes status, url, method, safe headers, and responseBody in error details."""
    respx.get("https://api.test.com/v1/data").mock(
        return_value=httpx.Response(
            401,
            json={"error": "invalid_token", "error_description": "Token has expired or is revoked"},
            headers={"Content-Type": "application/json", "X-Request-Id": "req_123"},
        )
    )

    node = HTTPRequestNode()
    params = HTTPRequestParams(
        url="https://api.test.com/v1/data",
        method="GET",
        authentication="none",
    )

    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(node_context, params, [{}])

    err = exc_info.value
    assert err.code == "AUTH_UNAUTHORIZED"
    assert "401" in str(err)
    assert err.details["statusCode"] == 401
    assert err.details["url"] == "https://api.test.com/v1/data"
    assert err.details["method"] == "GET"
    assert err.details["headers"]["x-request-id"] == "req_123"
    assert err.details["body"] == {"error": "invalid_token", "error_description": "Token has expired or is revoked"}


@pytest.mark.asyncio
@respx.mock
async def test_upstream_token_auto_fallback(node_context):
    """Problem 2 & 3: If Bearer Auth is selected with empty token, auto-bind upstream access_token."""
    respx.get("https://api.test.com/v1/protected").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    node = HTTPRequestNode()
    # auth_type is bearer, but auth_token is left empty
    params = HTTPRequestParams(
        url="https://api.test.com/v1/protected",
        method="GET",
        authentication="generic",
        auth_type="bearer",
        auth_token="",
    )

    # Input item contains access_token from previous step
    input_item = {"access_token": "secret_upstream_token_abc123"}
    res = await node.run(node_context, params, [input_item])

    assert len(res.output_items) == 1
    assert res.output_items[0]["body"] == {"status": "ok"}

    # Verify that the outgoing request had Authorization: Bearer secret_upstream_token_abc123
    assert respx.calls.last.request.headers["authorization"] == "Bearer secret_upstream_token_abc123"


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_hooks_on_init_and_on_success(node_context):
    """Suggestion 2: on_init pre-request headers and on_success post-response expression."""
    respx.get("https://api.test.com/v1/users").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]},
        )
    )

    node = HTTPRequestNode()
    params = HTTPRequestParams(
        url="https://api.test.com/v1/users",
        method="GET",
        on_init_headers={"X-Custom-Trace": "trace_xyz", "X-Client": "Flowsmith"},
        on_success_expression="{{ $response.body.data }}",
    )

    res = await node.run(node_context, params, [{}])

    # Check on_init_headers injected into request
    assert respx.calls.last.request.headers["x-custom-trace"] == "trace_xyz"
    assert respx.calls.last.request.headers["x-client"] == "Flowsmith"

    # Check on_success_expression unwrapped the list
    assert len(res.output_items) == 2
    assert res.output_items[0]["name"] == "Alice"
    assert res.output_items[1]["name"] == "Bob"


@pytest.mark.asyncio
@respx.mock
async def test_lifecycle_hook_on_error_fallback(node_context):
    """Suggestion 2: on_error_action fallback_data returns custom data without failing step."""
    respx.get("https://api.test.com/v1/external-service").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    node = HTTPRequestNode()
    params = HTTPRequestParams(
        url="https://api.test.com/v1/external-service",
        method="GET",
        on_error_action="fallback_data",
        on_error_fallback={"cached": True, "users": []},
    )

    # Should not raise exception
    res = await node.run(node_context, params, [{}])
    assert len(res.output_items) == 1
    assert res.output_items[0]["cached"] is True
    assert res.output_items[0]["users"] == []


@pytest.mark.asyncio
async def test_set_variable_node_execution(node_context):
    """Suggestion 3: SetVariableNode sets runtime expressions and persists to $env context."""
    node = SetVariableNode()
    params = SetVariableParams(
        variables=[
            {"key": "CURSOR_ID", "value": "{{ $json.next_cursor }}", "scope": "workflow"},
            {"key": "LAST_SYNCED", "value": "2026-09-23", "scope": "workflow"},
        ]
    )

    input_item = {"next_cursor": "cursor_999", "records": [1, 2, 3]}
    res = await node.run(node_context, params, [input_item])

    assert len(res.output_items) == 1
    assert res.output_items[0]["CURSOR_ID"] == "cursor_999"
    assert res.output_items[0]["LAST_SYNCED"] == "2026-09-23"
    assert node_context.expression_context["$env"]["CURSOR_ID"] == "cursor_999"
    assert node_context.expression_context["$env"]["LAST_SYNCED"] == "2026-09-23"


@pytest.mark.asyncio
async def test_auto_repair_recovers_401_with_upstream_token():
    """Problem 6: AI auto-repair automatically proposes binding upstream access token on 401 error."""
    from app.ai.assistant import repair_node_failure

    result = await repair_node_failure(
        node_type="http_request",
        operation=None,
        current_parameters={
            "url": "https://api.test.com/data",
            "method": "GET",
            "authentication": "generic",
            "auth_type": "bearer",
            "auth_token": "",
        },
        error_message="Authentication failed (HTTP 401 Unauthorized): Invalid or missing token",
        upstream_sample={"access_token": "token_abc_123"},
        chat=None,
        llm=None,
    )

    assert "401" in result["root_cause"]
    assert result["suggested_parameters"]["auth_token"] == "{{ $json.access_token }}"
    assert "access_token" in result["changes_summary"]

