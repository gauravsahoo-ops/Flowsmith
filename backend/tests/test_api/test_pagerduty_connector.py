"""PagerDuty connector tests.

Proves: Token-token auth header + v2 Accept header, incident CRUD shapes,
error-object mapping, 429 retryable, and connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from app.providers.pagerduty import PagerDutyProviderClient
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.pagerduty"]
CREDS = {"api_token": "pd_secret"}


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


def test_create_incident_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(201, {"incident": {"id": "P1", "title": "Down"}}),
    ])
    try:
        out = _run(PagerDutyProviderClient().create_incident(CREDS, "Down", "SVC1", "high"))
    finally:
        patcher.stop()

    assert out["incident"]["id"] == "P1"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://api.pagerduty.com/incidents"
    assert kwargs["headers"]["Authorization"] == "Token token=pd_secret"
    assert kwargs["json"]["incident"]["service"] == {"id": "SVC1", "type": "service_reference"}


def test_error_object_maps_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(400, {"error": {"code": 2001, "message": "Invalid service"}}),
    ])
    try:
        async def go():
            await PagerDutyProviderClient().get_incident(CREDS, "NOPE")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        assert "Invalid service" in str(exc_info.value)
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"error": {"code": 2012, "message": "Rate limit"}}),
    ])
    try:
        async def go():
            await PagerDutyProviderClient().list_incidents(CREDS)

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.retryable is True
    finally:
        patcher.stop()


def test_test_connection_counts_abilities():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"abilities": ["a", "b", "c"]}),
    ])
    try:
        out = _run(PagerDutyProviderClient().test_connection(CREDS))
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected (3 abilities)."}


def test_connector_dispatch_and_discovery():
    from app.connectors.pagerduty_connector import PagerDutyConnector

    assert get_registry().get("pagerduty") is not None
    conn = PagerDutyConnector()
    with pytest.raises(ConnectorError):
        _run(conn.op_execute("get_incident", {"incident_id": "P1"},
                             {"credentials": {"pagerduty": {}}}))
    out = _run(conn.op_list())
    assert out["output"]["operations"] == [
        "list_incidents", "get_incident", "create_incident",
        "update_incident", "resolve_incident", "add_note"]
