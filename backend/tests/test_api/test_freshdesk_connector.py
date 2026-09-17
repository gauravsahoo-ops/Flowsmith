"""Freshdesk connector tests.

Proves: email/token Basic auth + subdomain shaping, ticket CRUD shapes,
description mapping, 429 retryable, and connector op dispatch.
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.freshdesk"]
CREDS = {"email": "agent@acme.com", "api_token": "fd_secret", "domain": "acme"}


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


def test_create_ticket_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(201, {"id": 5, "subject": "Down"}),
    ])
    try:
        from app.providers.freshdesk import FreshdeskProviderClient

        out = _run(FreshdeskProviderClient().create_ticket(
            CREDS, "Down", "it broke", "user@x.com", priority=3))
    finally:
        patcher.stop()

    assert out["id"] == 5
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://acme.freshdesk.com/api/v2/tickets"
    expected = base64.b64encode(b"fd_secret:X").decode()
    assert kwargs["headers"]["Authorization"] == f"Basic {expected}"
    assert kwargs["json"] == {
        "subject": "Down", "description": "it broke",
        "email": "user@x.com", "priority": 3,
    }


def test_list_tickets_unwraps_bare_list():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, [{"id": 1}, {"id": 2}]),
    ])
    try:
        from app.providers.freshdesk import FreshdeskProviderClient

        out = _run(FreshdeskProviderClient().list_tickets(CREDS))
    finally:
        patcher.stop()

    assert [t["id"] for t in out["tickets"]] == [1, 2]
    _, _, kwargs = fake.calls[0]
    assert kwargs["params"] == {"per_page": 25}


def test_description_maps_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(404, {"description": "Not found", "code": "not_found"}),
    ])
    try:
        from app.providers.freshdesk import FreshdeskProviderClient

        async def go():
            await FreshdeskProviderClient().get_ticket(CREDS, "999")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.code in (ConnectorErrorCode.NOT_FOUND, ConnectorErrorCode.NOT_FOUND.value)
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"description": "Rate limited"}),
    ])
    try:
        from app.providers.freshdesk import FreshdeskProviderClient

        async def go():
            await FreshdeskProviderClient().list_tickets(CREDS)

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.retryable is True
    finally:
        patcher.stop()


def test_test_connection_reports_agent():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"contact": {"name": "Ada Agent"}}),
    ])
    try:
        from app.providers.freshdesk import FreshdeskProviderClient

        out = _run(FreshdeskProviderClient().test_connection(CREDS))
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected as Ada Agent."}


def test_connector_dispatch_and_discovery():
    from app.connectors.freshdesk_connector import FreshdeskConnector

    assert get_registry().get("freshdesk") is not None
    conn = FreshdeskConnector()
    with pytest.raises(ConnectorError):
        _run(conn.op_execute("get_ticket", {"ticket_id": "1"},
                             {"credentials": {"freshdesk": {}}}))
    out = _run(conn.op_list())
    assert out["output"]["operations"] == [
        "list_tickets", "get_ticket", "create_ticket", "update_ticket", "add_note"]
