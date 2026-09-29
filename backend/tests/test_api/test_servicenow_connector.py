"""ServiceNow connector tests.

Proves: instance shaping + Basic/Bearer auth, Table API CRUD shapes,
error mapping, 429 retryable, and connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from app.providers.servicenow import ServiceNowProviderClient
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.servicenow"]
CREDS = {"instance": "acme", "username": "admin", "password": "sn_secret"}


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


def test_list_records_query_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"result": [{"sys_id": "abc"}]}),
    ])
    try:
        out = _run(ServiceNowProviderClient().list_records(CREDS, "incident", query="active=true", limit=10))
    finally:
        patcher.stop()

    assert out["result"][0]["sys_id"] == "abc"
    method, url, kwargs = fake.calls[0]
    assert method == "GET"
    assert url == "https://acme.service-now.com/api/now/table/incident"
    assert kwargs["params"]["sysparm_query"] == "active=true"
    assert kwargs["params"]["sysparm_limit"] == "10"
    assert kwargs["headers"]["Authorization"].startswith("Basic ")


def test_bearer_auth_preferred():
    creds = {"instance": "https://acme.service-now.com", "access_token": "tok123"}
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"result": {"sys_id": "x"}}),
    ])
    try:
        _run(ServiceNowProviderClient().get_record(creds, "incident", "x"))
    finally:
        patcher.stop()

    _, url, kwargs = fake.calls[0]
    assert url == "https://acme.service-now.com/api/now/table/incident/x"
    assert kwargs["headers"]["Authorization"] == "Bearer tok123"


def test_create_record_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(201, {"result": {"sys_id": "n1", "short_description": "Help"}}),
    ])
    try:
        out = _run(ServiceNowProviderClient().create_record(CREDS, "incident", {"short_description": "Help"}))
    finally:
        patcher.stop()

    assert out["result"]["sys_id"] == "n1"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://acme.service-now.com/api/now/table/incident"
    assert kwargs["json"] == {"short_description": "Help"}


def test_update_uses_patch():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"result": {"sys_id": "n1", "state": "2"}}),
    ])
    try:
        _run(ServiceNowProviderClient().update_record(CREDS, "incident", "n1", {"state": "2"}))
    finally:
        patcher.stop()

    method, url, kwargs = fake.calls[0]
    assert method == "PATCH"
    assert url.endswith("/incident/n1")
    assert kwargs["json"] == {"state": "2"}


def test_delete_returns_confirmation():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(204, {}),
    ])
    # Fake 204 with json body {} still parses; also test empty path via provider normalization
    try:
        out = _run(ServiceNowProviderClient().delete_record(CREDS, "incident", "n1"))
    finally:
        patcher.stop()
    assert out["result"]["deleted"] is True


def test_auth_failure_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, {"error": {"message": "Unauthorized"}}),
    ])
    try:
        async def go():
            await ServiceNowProviderClient().get_record(
                {"instance": "acme", "username": "a", "password": "BAD"}, "incident", "1")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"error": {"message": "Rate limited"}}),
    ])
    try:
        async def go():
            await ServiceNowProviderClient().list_records(CREDS, "incident")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.retryable is True
    finally:
        patcher.stop()


def test_connector_dispatch_and_discovery():
    from app.connectors.servicenow_connector import ServiceNowConnector

    assert get_registry().get("servicenow") is not None
    conn = ServiceNowConnector()
    with pytest.raises(ConnectorError):
        _run(conn.op_execute("get_record", {"table": "incident", "sys_id": "1"},
                             {"credentials": {"servicenow": {}}}))
    out = _run(conn.op_list())
    assert out["output"]["operations"] == [
        "list_records", "get_record", "create_record", "update_record", "delete_record"]
