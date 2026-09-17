"""Todoist connector tests.

Proves: Bearer auth, task CRUD shapes, 204-close handling, 429 retryable,
and connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from app.providers.todoist import TodoistProviderClient
from tests.test_api._connector_fakes import empty_response, json_response, patch_provider_http

MODULE = ["app.providers.todoist"]
CREDS = {"api_token": "td_secret"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_create_task_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"id": "T1", "content": "Ship it"}),
    ])
    try:
        out = _run(TodoistProviderClient().create_task(CREDS, "Ship it", "desc"))
    finally:
        patcher.stop()

    assert out["id"] == "T1"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://api.todoist.com/api/v2/tasks"
    assert kwargs["headers"]["Authorization"] == "Bearer td_secret"
    assert kwargs["json"] == {"content": "Ship it", "description": "desc"}


def test_close_task_handles_204():
    patcher, fake = patch_provider_http(MODULE, [
        empty_response(204),
    ])
    try:
        out = _run(TodoistProviderClient().close_task(CREDS, "T1"))
    finally:
        patcher.stop()

    assert out == {"ok": True, "id": "T1"}
    method, url, _ = fake.calls[0]
    assert method == "POST"
    assert url == "https://api.todoist.com/api/v2/tasks/T1/close"


def test_auth_failure_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, "Unauthorized"),
    ])
    try:
        async def go():
            await TodoistProviderClient().get_task({"api_token": "BAD"}, "T1")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, "Too Many Requests"),
    ])
    try:
        async def go():
            await TodoistProviderClient().list_tasks(CREDS)

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.retryable is True
    finally:
        patcher.stop()


def test_test_connection_lists_projects():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, [{"id": "P1"}, {"id": "P2"}]),
    ])
    try:
        # projects endpoint returns a bare list here; probe tolerates it.
        out = _run(TodoistProviderClient().test_connection(CREDS))
    finally:
        patcher.stop()

    assert out["ok"] is True


def test_connector_dispatch_and_discovery():
    from app.connectors.todoist_connector import TodoistConnector

    assert get_registry().get("todoist") is not None
    conn = TodoistConnector()
    with pytest.raises(ConnectorError):
        _run(conn.op_execute("get_task", {"task_id": "T1"},
                             {"credentials": {"todoist": {}}}))
    out = _run(conn.op_list())
    assert out["output"]["operations"] == [
        "list_tasks", "get_task", "create_task", "update_task", "close_task", "add_comment"]
