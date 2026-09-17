"""Mailchimp connector tests.

Proves: Basic-auth + datacenter shaping (parsed from key suffix),
audience/member shapes, success:false mapping, 429 retryable.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.mailchimp"]
CREDS = {"api_key": "abc123-us21"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_add_member_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"id": "MEM1", "email_address": "a@x.com", "status": "subscribed"}),
    ])
    try:
        from app.providers.mailchimp import MailchimpProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            MailchimpProviderClient().add_member(CREDS, "AUD1", "a@x.com")
        )
    finally:
        patcher.stop()

    assert out["id"] == "MEM1"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://us21.api.mailchimp.com/3.0/lists/AUD1/members"
    assert kwargs["headers"]["Authorization"].startswith("Basic ")
    assert kwargs["json"] == {"email_address": "a@x.com", "status": "subscribed"}


def test_datacenter_override_wins():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"lists": []}),
    ])
    try:
        from app.providers.mailchimp import MailchimpProviderClient

        asyncio.new_event_loop().run_until_complete(
            MailchimpProviderClient().list_lists({"api_key": "k", "datacenter": "us7"})
        )
    finally:
        patcher.stop()

    _, url, _ = fake.calls[0]
    assert url.startswith("https://us7.api.mailchimp.com/3.0/lists")


def test_success_false_maps_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(404, {"title": "Resource Not Found", "detail": "The requested list was not found."}),
    ])
    try:
        from app.providers.mailchimp import MailchimpProviderClient

        async def go():
            await MailchimpProviderClient().get_list(CREDS, "NOPE")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("404 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.NOT_FOUND, ConnectorErrorCode.NOT_FOUND.value)
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"title": "Too Many Requests"}),
    ])
    try:
        from app.providers.mailchimp import MailchimpProviderClient

        async def go():
            await MailchimpProviderClient().list_lists(CREDS)

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


def test_test_connection_reports_account():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"account_id": "ACC1", "account_name": "Acme"}),
    ])
    try:
        from app.providers.mailchimp import MailchimpProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            MailchimpProviderClient().test_connection(CREDS)
        )
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected (account ACC1)."}


def test_connector_dispatch_and_discovery():
    import pytest as _pytest

    from app.connectors.mailchimp_connector import MailchimpConnector

    assert get_registry().get("mailchimp") is not None
    conn = MailchimpConnector()
    with _pytest.raises(ConnectorError):
        asyncio.new_event_loop().run_until_complete(
            conn.op_execute("get_list", {"list_id": "L1"},
                            {"credentials": {"mailchimp": {}}})
        )
    assert asyncio.new_event_loop().run_until_complete(
        conn.op_list())["output"]["operations"] == [
        "list_lists", "get_list", "add_member", "get_member", "update_member"]
