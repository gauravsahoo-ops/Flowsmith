"""Engine credential resolution tests (spec 12, 29): $cred expressions,
missing credentials, resolver wiring."""

from __future__ import annotations

import httpx
import respx

from app.engine.errors import NodeExecutionError
from app.engine.executor import execute_workflow
from tests.conftest import conn, make_node, make_workflow


async def test_http_node_resolves_cred_expression(respx_mock):
    respx_mock.get("https://api.example.com/data").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node(
                "http",
                "http_request",
                parameters={
                    "method": "GET",
                    "url": "https://api.example.com/data",
                    "headers": {"X-Api-Key": "{{ $cred.http.api_key }}", "Authorization": "Bearer {{ $cred.http.password }}"},
                },
            ),
        ],
        [conn("trigger", "http")],
    )
    wf.nodes[1].credentials = {"http": "cred_1"}

    result = await execute_workflow(
        wf,
        credential_resolver=lambda refs: {
            "http": {"api_key": "k123", "password": "p456", "username": ""}
        },
    )
    assert result.status == "success"
    request = respx_mock.calls[0].request
    assert request.headers["X-Api-Key"] == "k123"
    assert request.headers["Authorization"] == "Bearer p456"


async def test_node_without_credentials_map_gets_empty_ctx(respx_mock):
    respx_mock.get("https://api.example.com/data").mock(return_value=httpx.Response(200, json={}))
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node(
                "http",
                "http_request",
                parameters={
                    "method": "GET",
                    "url": "https://api.example.com/data",
                    "headers": {"X-Api-Key": "{{ $cred.http.api_key }}"},
                },
            ),
        ],
        [conn("trigger", "http")],
    )
    wf.nodes[1].credentials = {}

    result = await execute_workflow(
        wf, credential_resolver=lambda refs: {"http": {"api_key": "k"}}
    )

    assert result.status == "success"
    # unresolved expression stays visible in the request header as text
    request = respx.calls[0].request
    assert "{{" in request.headers["X-Api-Key"]


async def test_missing_credential_fails_node():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("email", "send_email", parameters={
                "to": "a@b.com", "subject": "Hi", "body": "x", "from_address": "me@x.com",
            }),
        ],
        [conn("trigger", "email")],
    )
    wf.nodes[1].credentials = {"smtp": "cred_missing"}

    def failing_resolver(refs):
        raise NodeExecutionError(
            "Credential 'cred_missing' for 'smtp' not found or not yours.",
            code="CREDENTIALS_REQUIRED",
        )

    result = await execute_workflow(wf, credential_resolver=failing_resolver)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "CREDENTIALS_REQUIRED"
    assert result.error.node_id == "email"


async def test_resolver_receives_node_credential_refs(respx_mock):
    seen: dict = {}

    def resolver(refs):
        seen.update(refs)
        return {}

    respx_mock.get("https://x.example/").mock(return_value=httpx.Response(200, json={}))
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("http", "http_request", parameters={"method": "GET", "url": "https://x.example/"}),
        ],
        [conn("trigger", "http")],
    )
    wf.nodes[1].credentials = {"http": "cred_9"}

    result = await execute_workflow(wf, credential_resolver=resolver)

    assert result.status == "success"
    assert seen == {"http": "cred_9"}


async def test_no_resolver_passed_is_safe():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("set", "set_data", parameters={"fields": {"a": 1}}),
        ],
        [conn("trigger", "set")],
    )
    wf.nodes[1].credentials = {"http": "cred_1"}
    result = await execute_workflow(wf)
    assert result.status == "success"


async def test_db_credential_available_in_ctx():
    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node("db", "database_query", parameters={"sql": "SELECT 1"}),
        ],
        [conn("trigger", "db")],
    )
    wf.nodes[1].credentials = {"database": "cred_db"}

    def resolver(refs):
        return {"database": {"dsn": "sqlite://"}}

    result = await execute_workflow(wf, credential_resolver=resolver)
    assert result.status == "success"
    assert result.results["db"]["main"] == [{"1": 1}]
