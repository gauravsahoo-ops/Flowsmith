"""Discord connector tests (Phase 11 business connectors).

Proves: Bot auth scheme for channel messages, webhook mode without a
stored credential, 2000-char cap, 429 Retry-After mapping.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import empty_response, json_response, patch_provider_http

MODULE = ["app.providers.discord", "app.providers.base"]
CREDS = {"bot_token": "discord-bot-token-secret"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_send_message_uses_bot_scheme():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"id": "m-9"}),
    ])
    try:
        from app.providers.discord import DiscordProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            DiscordProviderClient().send_message(CREDS, "123456789", "deploy done")
        )
    finally:
        patcher.stop()

    assert out["sent"] is True
    _, url, kwargs = fake.calls[0]
    assert url == "https://discord.com/api/v10/channels/123456789/messages"
    assert kwargs["headers"]["Authorization"] == f"Bot {CREDS['bot_token']}"


def test_send_webhook_needs_no_credential():
    patcher, fake = patch_provider_http(MODULE, [
        empty_response(204),
    ])
    try:
        from app.providers.discord import DiscordProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            DiscordProviderClient().send_webhook(
                "https://discord.com/api/webhooks/1/xyz", "alert!", username="robot",
            )
        )
    finally:
        patcher.stop()

    assert out["status"] == 204
    method, url, kwargs = fake.calls[0]
    assert not (kwargs.get("headers") or {}).get("Authorization")
    assert kwargs["json"] == {"content": "alert!", "username": "robot"}


def test_content_length_cap_enforced_locally():
    from app.providers.discord import DiscordProviderClient

    async def go():
        await DiscordProviderClient().send_message(CREDS, "123", "x" * 2001)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("oversized content should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        assert "2000" in str(exc)
    finally:
        loop.close()


def test_webhook_rate_limit_maps_with_delay():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"message": "You are being rate limited."}, headers={"Retry-After": "2.5"}),
    ])
    try:
        from app.providers.discord import DiscordProviderClient

        async def go():
            await DiscordProviderClient().send_webhook("https://discord.com/api/webhooks/1/x", "hi")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("429 should have raised")
        except ConnectorError as exc:
            assert exc.retryable is True
            assert exc.retry_after == 2.5
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_non_https_webhook_rejected():
    from app.providers.discord import DiscordProviderClient

    async def go():
        await DiscordProviderClient().send_webhook("http://evil.example/hook", "hi")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("http webhook should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
    finally:
        loop.close()
