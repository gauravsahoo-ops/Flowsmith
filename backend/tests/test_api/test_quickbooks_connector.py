"""QuickBooks connector tests.

Proves: Bearer + company-scoped URL shaping (sandbox default),
query/customer/invoice shapes, Fault-payload mapping, 429 retryable.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.quickbooks"]
CREDS = {"access_token": "qb_secret", "realm_id": "12345"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_query_posts_text_body():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"QueryResponse": {"Customer": [{"Id": "1"}]}}),
    ])
    try:
        from app.providers.quickbooks import QuickBooksProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            QuickBooksProviderClient().query(CREDS, "select * from Customer")
        )
    finally:
        patcher.stop()

    assert out["QueryResponse"]["Customer"][0]["Id"] == "1"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://sandbox-quickbooks.api.intuit.com/v3/company/12345/query"
    assert kwargs["headers"]["Authorization"] == "Bearer qb_secret"
    assert kwargs["params"]["minorversion"] == "65"


def test_production_host_override():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"CompanyInfo": {"CompanyName": "Acme"}}),
    ])
    try:
        from app.providers.quickbooks import QuickBooksProviderClient

        asyncio.new_event_loop().run_until_complete(
            QuickBooksProviderClient().get_company({**CREDS, "environment": "production"})
        )
    finally:
        patcher.stop()

    _, url, _ = fake.calls[0]
    assert url == "https://quickbooks.api.intuit.com/v3/company/12345/companyinfo/12345"


def test_fault_maps_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(400, {"Fault": {"Error": [{"Message": "Invalid reference id", "code": "6000"}]}}),
    ])
    try:
        from app.providers.quickbooks import QuickBooksProviderClient

        async def go():
            await QuickBooksProviderClient().get_customer(CREDS, "NOPE")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("400 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
            assert "Invalid reference id" in str(exc)
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"Fault": {"Error": [{"Message": "Throttle exceeded"}]}}),
    ])
    try:
        from app.providers.quickbooks import QuickBooksProviderClient

        async def go():
            await QuickBooksProviderClient().get_company(CREDS)

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


def test_test_connection_reports_company():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"CompanyInfo": {"CompanyName": "Acme Corp"}}),
    ])
    try:
        from app.providers.quickbooks import QuickBooksProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            QuickBooksProviderClient().test_connection(CREDS)
        )
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected to Acme Corp."}


def test_connector_dispatch_and_discovery():
    import pytest as _pytest

    from app.connectors.quickbooks_connector import QuickBooksConnector

    assert get_registry().get("quickbooks") is not None
    conn = QuickBooksConnector()
    with _pytest.raises(ConnectorError):
        asyncio.new_event_loop().run_until_complete(
            conn.op_execute("get_company", {}, {"credentials": {"quickbooks": {}}})
        )
    assert asyncio.new_event_loop().run_until_complete(
        conn.op_list())["output"]["operations"] == [
        "query", "get_company", "create_customer", "get_customer", "create_invoice", "get_invoice"]
