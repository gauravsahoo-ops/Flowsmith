"""Zendesk connector tests.

Proves: email/token Basic auth + subdomain shaping, ticket CRUD shapes,
error mapping, 429 retryable, and connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from app.providers.zendesk import ZendeskProviderClient
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.zendesk"]
CREDS = {"email": "agent@acme.com", "api_token": "zd_secret", "subdomain": "acme"}


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
        json_response(201, {"ticket": {"id": 42, "subject": "Help"}}),
    ])
    try:
        out = _run(ZendeskProviderClient().create_ticket(CREDS, "Help", "broken", "urgent"))
    finally:
        patcher.stop()

    assert out["ticket"]["id"] == 42
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://acme.zendesk.com/api/v2/tickets.json"
    assert kwargs["headers"]["Authorization"].startswith("Basic ")
    assert kwargs["json"] == {"ticket": {"subject": "Help", "comment": {"body": "broken"}, "priority": "urgent"}}


def test_subdomain_prefix_stripped():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"tickets": []}),
    ])
    try:
        _run(ZendeskProviderClient().list_tickets({**CREDS, "subdomain": "https://acme.zendesk.com"}))
    finally:
        patcher.stop()

    _, url, _ = fake.calls[0]
    assert url == "https://acme.zendesk.com/api/v2/tickets.json"


def test_auth_failure_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, {"error": "Couldn't authenticate you"}),
    ])
    try:
        async def go():
            await ZendeskProviderClient().get_ticket(
                {"email": "a@b.c", "api_token": "BAD", "subdomain": "acme"}, "1")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"error": "Rate limited"}),
    ])
    try:
        async def go():
            await ZendeskProviderClient().list_tickets(CREDS)

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.retryable is True
    finally:
        patcher.stop()


def test_test_connection_reports_user():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"user": {"id": 9, "name": "Ada Agent"}}),
    ])
    try:
        out = _run(ZendeskProviderClient().test_connection(CREDS))
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected as Ada Agent."}


def test_connector_dispatch_and_discovery():
    from app.connectors.zendesk_connector import ZendeskConnector

    assert get_registry().get("zendesk") is not None
    conn = ZendeskConnector()
    with pytest.raises(ConnectorError):
        _run(conn.op_execute("get_ticket", {"ticket_id": "1"},
                             {"credentials": {"zendesk": {}}}))
    out = _run(conn.op_list())
    assert out["output"]["operations"] == [
        "list_tickets", "get_ticket", "create_ticket", "update_ticket", "add_comment"]
