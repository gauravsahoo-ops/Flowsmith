"""Pipedrive connector tests.

Proves: query-token auth + company domain URL shaping, deal CRUD shapes,
success:false mapping, 429 retryable, and connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.pipedrive"]
CREDS = {"api_token": "pd_secret", "domain": "acme.pipedrive.com"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_create_deal_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"success": True, "data": {"id": 1, "title": "Big one"}}),
    ])
    try:
        from app.providers.pipedrive import PipedriveProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            PipedriveProviderClient().create_deal(CREDS, "Big one", "5000", "USD")
        )
    finally:
        patcher.stop()

    assert out["data"]["id"] == 1
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://acme.pipedrive.com/api/v1/deals"
    assert kwargs["params"]["api_token"] == "pd_secret"
    assert kwargs["json"] == {"title": "Big one", "value": "5000", "currency": "USD"}


def test_success_false_maps_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"success": False, "error": "Deal not found"}),
    ])
    try:
        from app.providers.pipedrive import PipedriveProviderClient

        async def go():
            await PipedriveProviderClient().get_deal(CREDS, "999")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("success:false should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
            assert "Deal not found" in str(exc)
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_auth_failure_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, {"success": False, "error": "Invalid token"}),
    ])
    try:
        from app.providers.pipedrive import PipedriveProviderClient

        async def go():
            await PipedriveProviderClient().list_deals({"api_token": "BAD", "domain": "x.pipedrive.com"})

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
        json_response(429, {"success": False, "error": "Rate limit"}),
    ])
    try:
        from app.providers.pipedrive import PipedriveProviderClient

        async def go():
            await PipedriveProviderClient().list_deals(CREDS)

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
        json_response(200, {"success": True, "data": {"name": "Gaurav"}}),
    ])
    try:
        from app.providers.pipedrive import PipedriveProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            PipedriveProviderClient().test_connection(CREDS)
        )
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected as Gaurav."}


def test_connector_dispatch_and_discovery():
    import pytest as _pytest

    from app.connectors.pipedrive_connector import PipedriveConnector

    assert get_registry().get("pipedrive") is not None
    conn = PipedriveConnector()
    with _pytest.raises(ConnectorError):
        asyncio.new_event_loop().run_until_complete(
            conn.op_execute("get_deal", {"deal_id": "1"},
                            {"credentials": {"pipedrive": {}}})
        )
    assert asyncio.new_event_loop().run_until_complete(
        conn.op_list())["output"]["operations"] == [
        "list_deals", "get_deal", "create_deal", "update_deal", "add_note"]
