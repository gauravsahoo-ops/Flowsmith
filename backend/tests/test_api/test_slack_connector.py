"""Slack connector tests (Phase 11 business connectors).

Proves: bot-token auth, chat.postMessage shape, app-level error mapping
(Slack returns 200 + ok:false), rate_limited with Retry-After surfaced
for the engine, cursor pagination on conversations.list.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.base"]
CREDS = {"bot_token": "xoxb-secret-token"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_send_message_posts_with_bot_token():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"ok": True, "ts": "1717000000.000100", "channel": "C123"}),
    ])
    try:
        from app.providers.slack import SlackProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            SlackProviderClient().send_message(CREDS, "C123", "hello from the workflow")
        )
    finally:
        patcher.stop()

    assert out["sent"] is True and out["ts"].startswith("17")
    method, url, kwargs = fake.calls[0]
    assert url == "https://slack.com/api/chat.postMessage"
    assert kwargs["headers"]["Authorization"] == "Bearer xoxb-secret-token"
    assert kwargs["json"] == {"channel": "C123", "text": "hello from the workflow"}


def test_slack_app_error_maps_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"ok": False, "error": "channel_not_found"}),
    ])
    try:
        from app.providers.slack import SlackProviderClient

        async def go():
            await SlackProviderClient().send_message(CREDS, "C_MISSING", "hi")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("ok:false should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
            assert "channel_not_found" in str(exc)
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_rate_limited_carries_retry_after():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"ok": False, "error": "rate_limited"}, headers={"Retry-After": "30"}),
    ])
    try:
        from app.providers.slack import SlackProviderClient

        async def go():
            await SlackProviderClient().send_message(CREDS, "C1", "hi")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("rate_limited should have raised")
        except ConnectorError as exc:
            assert exc.retryable is True
            assert exc.retry_after == 30.0
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_list_channels_follows_cursor_pagination():
    page1 = {
        "ok": True,
        "channels": [{"id": "C1", "name": "general"}],
        "response_metadata": {"next_cursor": "CURSOR_2"},
    }
    page2 = {
        "ok": True,
        "channels": [{"id": "C2", "name": "random"}],
        "response_metadata": {"next_cursor": ""},
    }
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, page1),
        json_response(200, page2),
    ])
    try:
        from app.providers.slack import SlackProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            SlackProviderClient().list_channels(CREDS, max_pages=3)
        )
    finally:
        patcher.stop()

    assert [c["id"] for c in out["channels"]] == ["C1", "C2"]
    _, _, kwargs2 = fake.calls[1]
    assert kwargs2["params"]["cursor"] == "CURSOR_2"


def test_missing_bot_token_is_not_configured():
    from app.providers.slack import SlackProviderClient

    async def go():
        await SlackProviderClient().send_message({}, "C1", "hi")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("missing token should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
    finally:
        loop.close()


def test_connector_routes_send_and_list(monkeypatch):
    """The connector layer maps operations onto provider calls."""
    from app.connectors.slack_connector import SlackConnector
    from app.providers.slack import SlackProviderClient

    conn = SlackConnector()

    async def fake_send(creds, channel, text, thread_ts="", timeout=30.0):
        return {"ts": "12", "channel": channel, "sent": True}

    monkeypatch.setattr(conn._provider, "send_message", fake_send)

    async def go():
        return await conn.op_execute(
            "", {"operation": "send_message", "channel": "C9", "text": "go"},
            {"credentials": {"slack": CREDS}},
        )

    out = asyncio.new_event_loop().run_until_complete(go())
    assert out["channel"] == "C9"
