"""Brevo connector tests.

Proves: api-key header auth, SMTP send shape, contact CRUD, message
mapping, 429 retryable, and connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.brevo"]
CREDS = {"api_key": "xkeysib_test"}


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


def test_send_email_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(201, {"messageId": "MSG1"}),
    ])
    try:
        from app.providers.brevo import BrevoProviderClient

        out = _run(BrevoProviderClient().send_email(
            CREDS, "a@x.com", "b@x.com", "Hi", html="<b>Hi</b>"))
    finally:
        patcher.stop()

    assert out["messageId"] == "MSG1"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://api.sendinblue.com/v3/smtp/email"
    assert kwargs["headers"]["api-key"] == "xkeysib_test"
    assert kwargs["json"]["to"] == [{"email": "b@x.com"}]
    assert kwargs["json"]["htmlContent"] == "<b>Hi</b>"


def test_create_contact_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(201, {"id": 7}),
    ])
    try:
        from app.providers.brevo import BrevoProviderClient

        out = _run(BrevoProviderClient().create_contact(CREDS, "c@x.com"))
    finally:
        patcher.stop()

    assert out["id"] == 7
    _, url, kwargs = fake.calls[0]
    assert url == "https://api.sendinblue.com/v3/contacts"
    assert kwargs["json"] == {"email": "c@x.com"}


def test_message_maps_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(400, {"code": "invalid_parameter", "message": "Bad email"}),
    ])
    try:
        from app.providers.brevo import BrevoProviderClient

        async def go():
            await BrevoProviderClient().get_contact(CREDS, "not-an-email")

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        assert "Bad email" in str(exc_info.value)
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"code": "too_many_requests", "message": "Slow down"}),
    ])
    try:
        from app.providers.brevo import BrevoProviderClient

        async def go():
            await BrevoProviderClient().list_contacts(CREDS)

        with pytest.raises(ConnectorError) as exc_info:
            _run(go())
        assert exc_info.value.retryable is True
    finally:
        patcher.stop()


def test_test_connection_reports_account():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"email": "owner@x.com", "firstName": "O"}),
    ])
    try:
        from app.providers.brevo import BrevoProviderClient

        out = _run(BrevoProviderClient().test_connection(CREDS))
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected as owner@x.com."}


def test_connector_dispatch_and_discovery():
    from app.connectors.brevo_connector import BrevoConnector

    assert get_registry().get("brevo") is not None
    conn = BrevoConnector()
    with pytest.raises(ConnectorError):
        _run(conn.op_execute("get_contact", {"email": "a@x.com"},
                             {"credentials": {"brevo": {}}}))
    out = _run(conn.op_list())
    assert out["output"]["operations"] == [
        "send_email", "list_contacts", "get_contact", "create_contact", "update_contact"]
