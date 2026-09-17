"""Monday.com connector tests.

Proves: Bearer token auth, GraphQL shapes, error mapping, 429 retryable,
missing-board handling, and connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.monday"]
CREDS = {"api_token": "mon_secret"}


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


def test_create_item_posts_graphql():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"data": {"create_item": {"id": "I9", "name": "Ship"}}}),
    ])
    try:
        from app.providers.monday import MondayProviderClient

        out = _run(MondayProviderClient().create_item(CREDS, "B1", "Ship"))
    finally:
        patcher.stop()

    assert out["item"]["id"] == "I9"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://api.monday.com/v2"
    assert kwargs["headers"]["Authorization"] == "mon_secret"
    assert "create_item" in kwargs["json"]["query"]
    assert kwargs["json"]["variables"]["name"] == "Ship"


def test_graphql_errors_map_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"errors": [{"message": "Invalid board"}]}),
    ])
    try:
        from app.providers.monday import MondayProviderClient

        async def go():
            await MondayProviderClient().get_board(CREDS, "NOPE")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        assert "Invalid board" in str(exc_info.value)
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"errors": [{"message": "Complexity budget exhausted"}]}),
    ])
    try:
        from app.providers.monday import MondayProviderClient

        async def go():
            await MondayProviderClient().list_boards(CREDS)

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.retryable is True
    finally:
        patcher.stop()


def test_missing_board_is_not_found():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"data": {"boards": []}}),
    ])
    try:
        from app.providers.monday import MondayProviderClient

        async def go():
            await MondayProviderClient().get_board(CREDS, "NOPE")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.code in (ConnectorErrorCode.NOT_FOUND, ConnectorErrorCode.NOT_FOUND.value)
    finally:
        patcher.stop()


def test_test_connection_reports_user():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"data": {"me": {"id": "3", "name": "Gaurav"}}}),
    ])
    try:
        from app.providers.monday import MondayProviderClient

        out = _run(MondayProviderClient().test_connection(CREDS))
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected as Gaurav."}


def test_connector_dispatch_and_discovery():
    from app.connectors.monday_connector import MondayConnector

    assert get_registry().get("monday") is not None
    conn = MondayConnector()
    with pytest.raises(ConnectorError):
        _run(conn.op_execute("get_board", {"board_id": "B1"},
                             {"credentials": {"monday": {}}}))
    out = _run(conn.op_list())
    assert out["output"]["operations"] == [
        "list_boards", "get_board", "list_items", "create_item", "add_update"]
