"""ClickUp connector tests.

Proves: PAT auth header, task CRUD shapes, ClickUp error mapping
(401 -> AUTH_FAILED), 429 retryable, test_connection user probe, and
connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.clickup"]
CREDS = {"api_key": "pk_clickup_secret"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_create_task_posts_clickup_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"id": "TASK1", "name": "Ship it"}),
    ])
    try:
        from app.providers.clickup import ClickUpProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            ClickUpProviderClient().create_task(CREDS, "LIST9", "Ship it", "desc")
        )
    finally:
        patcher.stop()

    assert out["id"] == "TASK1"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://api.clickup.com/api/v2/list/LIST9/task"
    assert kwargs["headers"]["Authorization"] == "pk_clickup_secret"
    assert kwargs["json"] == {"name": "Ship it", "description": "desc"}


def test_list_tasks_uses_query_params():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"tasks": [{"id": "T1"}]}),
    ])
    try:
        from app.providers.clickup import ClickUpProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            ClickUpProviderClient().list_tasks(CREDS, "LIST9", limit=10)
        )
    finally:
        patcher.stop()

    assert out["tasks"][0]["id"] == "T1"
    _, url, kwargs = fake.calls[0]
    assert url == "https://api.clickup.com/api/v2/list/LIST9/task"
    assert kwargs["params"]["limit"] == 10


def test_auth_failure_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, {"err": "Invalid token"}),
    ])
    try:
        from app.providers.clickup import ClickUpProviderClient

        async def go():
            await ClickUpProviderClient().get_task({"api_key": "BAD"}, "T1")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("401 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"err": "Rate limit reached"}),
    ])
    try:
        from app.providers.clickup import ClickUpProviderClient

        async def go():
            await ClickUpProviderClient().get_task(CREDS, "T1")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("429 should have raised")
        except ConnectorError as exc:
            assert exc.retryable is True
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_test_connection_returns_username():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"user": {"id": 7, "username": "ada"}}),
    ])
    try:
        from app.providers.clickup import ClickUpProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            ClickUpProviderClient().test_connection(CREDS)
        )
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected as ada."}


def test_connector_dispatch_and_discovery():
    import pytest as _pytest

    from app.connectors.clickup_connector import ClickUpConnector

    assert get_registry().get("clickup") is not None
    conn = ClickUpConnector()
    with _pytest.raises(ConnectorError):
        asyncio.new_event_loop().run_until_complete(
            conn.op_execute("get_task", {"task_id": "T1"},
                            {"credentials": {"clickup": {}}})
        )
    assert asyncio.new_event_loop().run_until_complete(
        conn.op_list())["output"]["operations"] == [
        "list_tasks", "get_task", "create_task", "update_task", "add_comment"]
