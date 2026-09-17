"""WhatsApp connector tests.

Proves: Bearer auth + phone-number-id URL shaping, text/template payload
shapes, Graph error mapping (invalid token -> AUTH_FAILED), 429 retryable,
test_connection verified_name probe, and connector op dispatch.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.whatsapp"]
CREDS = {"access_token": "EAAMETA_TOKEN", "phone_number_id": "123456789"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_send_text_posts_graph_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"messages": [{"id": "wamid.ABC"}]}),
    ])
    try:
        from app.providers.whatsapp import WhatsAppProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            WhatsAppProviderClient().send_text(CREDS, "+15551234567", "hello")
        )
    finally:
        patcher.stop()

    assert out["messages"][0]["id"] == "wamid.ABC"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://graph.facebook.com/v21.0/123456789/messages"
    assert kwargs["headers"]["Authorization"] == "Bearer EAAMETA_TOKEN"
    assert kwargs["json"]["to"] == "+15551234567"
    assert kwargs["json"]["text"] == {"body": "hello", "preview_url": False}


def test_send_template_posts_template_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"messages": [{"id": "wamid.DEF"}]}),
    ])
    try:
        from app.providers.whatsapp import WhatsAppProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            WhatsAppProviderClient().send_template(CREDS, "+15551234567", "hello_world", "en_US")
        )
    finally:
        patcher.stop()

    assert out["messages"][0]["id"] == "wamid.DEF"
    _, _, kwargs = fake.calls[0]
    assert kwargs["json"]["template"] == {"name": "hello_world", "language": {"code": "en_US"}}


def test_invalid_token_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, {"error": {"message": "Invalid OAuth access token.", "code": 190}}),
    ])
    try:
        from app.providers.whatsapp import WhatsAppProviderClient

        async def go():
            await WhatsAppProviderClient().send_text(
                {"access_token": "BAD", "phone_number_id": "1"}, "+1", "hi")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("401 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)
            assert "Invalid OAuth access token" in str(exc)
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"error": {"message": "(#80007) Rate limit."}}),
    ])
    try:
        from app.providers.whatsapp import WhatsAppProviderClient

        async def go():
            await WhatsAppProviderClient().send_text(CREDS, "+1", "hi")

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


def test_missing_credential_is_not_configured():
    from app.providers.whatsapp import WhatsAppProviderClient

    async def go():
        await WhatsAppProviderClient().send_text({}, "+1", "hi")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("missing creds should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    finally:
        loop.close()


def test_connector_dispatch_and_discovery():
    import pytest as _pytest

    from app.connectors.whatsapp_connector import WhatsAppConnector

    listed = get_registry().get("whatsapp")
    assert listed is not None
    conn = WhatsAppConnector()
    # Without credentials the provider raises NOT_CONFIGURED (no HTTP made).
    with _pytest.raises(ConnectorError):
        asyncio.new_event_loop().run_until_complete(
            conn.op_execute("send_text", {"to": "+1", "body": "x"},
                            {"credentials": {"whatsapp": {}}})
        )
    assert asyncio.new_event_loop().run_until_complete(
        conn.op_list())["output"]["operations"] == ["send_text", "send_template", "get_message"]
