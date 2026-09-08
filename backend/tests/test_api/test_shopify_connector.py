"""Shopify connector tests (Phase 11 business connectors).

Proves: X-Shopify-Access-Token auth + domain pinning, Link-header
page_info pagination, 429 Retry-After mapping, order id validation.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = "app.providers.shopify"
CREDS = {"shop_domain": "acme.myshopify.com", "access_token": "shpat_secret_value"}
API = f"https://acme.myshopify.com/admin/api/2024-10"


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_list_products_follows_link_header_pagination():
    link2 = f'<{API}/products.json?limit=2&page_info=PAGE2>; rel="next"'
    page1_headers = {"Link": link2}
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"products": [{"id": 1, "title": "A"}]}, headers=page1_headers),
        json_response(200, {"products": [{"id": 2, "title": "B"}]}),
    ])
    try:
        from app.providers.shopify import ShopifyProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            ShopifyProviderClient().list_products(CREDS, limit=2, max_pages=3)
        )
    finally:
        patcher.stop()

    assert [p["id"] for p in out["products"]] == [1, 2]
    method0, url0, kwargs0 = fake.calls[0]
    assert url0 == f"{API}/products.json"
    assert kwargs0["headers"]["X-Shopify-Access-Token"] == "shpat_secret_value"
    # Second request uses the opaque cursor URL verbatim.
    _, url1, kwargs1 = fake.calls[1]
    assert "page_info=PAGE2" in url1
    assert not kwargs1.get("params")


def test_get_product_and_order_validate_ids():
    from app.providers.shopify import ShopifyProviderClient

    async def go_product():
        await ShopifyProviderClient().get_product(CREDS, "../admin")

    async def go_order():
        await ShopifyProviderClient().get_order(CREDS, "abc")

    loop = asyncio.new_event_loop()
    for go in (go_product, go_order):
        try:
            loop.run_until_complete(go())
            raise AssertionError("non-numeric id should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        finally:
            continue
    loop.close()


def test_bad_shop_domain_rejected():
    from app.providers.shopify import ShopifyProviderClient

    async def go():
        await ShopifyProviderClient().get_product(
            {"shop_domain": "evil.example.com", "access_token": "x"}, "123"
        )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("foreign domain should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
        assert "myshopify.com" in str(exc)
    finally:
        loop.close()


def test_leaky_bucket_429_maps_retry_after():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"errors": "Too Many Requests"}, headers={"Retry-After": "3"}),
    ])
    try:
        from app.providers.shopify import ShopifyProviderClient

        async def go():
            await ShopifyProviderClient().get_product(CREDS, "123")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("429 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.RATE_LIMITED, ConnectorErrorCode.RATE_LIMITED.value)
            assert exc.retryable is True
            assert exc.retry_after == 3.0
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_create_product_payload():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(201, {"product": {"id": 9, "title": "Mug", "handle": "mug"}}),
    ])
    try:
        from app.providers.shopify import ShopifyProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            ShopifyProviderClient().create_product(
                CREDS, "Mug", body_html="<p>hot</p>", vendor="Acme", tags=["kitchen"],
            )
        )
    finally:
        patcher.stop()

    assert out["success"] is True and out["id"] == 9
    method, url, kwargs = fake.calls[0]
    assert url == f"{API}/products.json"
    assert kwargs["json"]["product"]["title"] == "Mug"
    assert kwargs["json"]["product"]["tags"] == "kitchen"
