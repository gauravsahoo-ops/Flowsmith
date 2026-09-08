"""Gmail connector tests (Phase 41): OAuth reuse, MIME building, taxonomy,
full-stack send with secret-leak check."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register


pytestmark = pytest.mark.timing

def _settings(**kw) -> Settings:
    return Settings(google_client_id="G_CID", google_client_secret="G_SECRET", **kw)


class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        pass

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _json(status, payload):
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch(responses):
    fake = FakeHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    p = patch("app.providers.base.get_safe_http_client", return_value=cm)
    p.start()
    return p, fake


CREDS = {"oauth": True, "refresh_token": "G_RT_SECRET_11", "user": "me@gmail.com"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    r = get_registry()
    r.initialize()
    register_builtin_connectors()
    monkeypatch.setattr("app.providers.gmail._get_settings", lambda: _settings())
    yield


# ----------------------------------------------------------------------
# Provider unit
# ----------------------------------------------------------------------

def test_send_builds_mime_and_posts_base64():
    patcher, fake = _patch([
        _json(200, {"access_token": "AT", "expires_in": 3600}),
        _json(200, {"id": "msg_1", "threadId": "th_1"}),
    ])
    try:
        from app.providers.gmail import GmailProviderClient

        result = asyncio.new_event_loop().run_until_complete(
            GmailProviderClient().send(
                CREDS, to="a@b.com, c@d.com", subject="Hi",
                body_text="<b>hello</b>", html=True,
            )
        )
    finally:
        patcher.stop()

    assert result["sent"] is True and result["id"] == "msg_1"
    m1, u1, k1 = fake.calls[0]
    assert u1.endswith("/token")
    m2, u2, k2 = fake.calls[1]
    assert u2.endswith("/gmail/v1/users/me/messages/send")
    # raw is base64url of a MIME message with headers + html body
    import base64
    mime = base64.urlsafe_b64decode(k2["json"]["raw"]).decode()
    assert "To: a@b.com, c@d.com" in mime
    assert "Subject: Hi" in mime
    assert "<b>hello</b>" in mime


def test_invalid_recipient_rejected_before_network():
    from app.providers.gmail import GmailProviderClient

    async def go():
        await GmailProviderClient().send(CREDS, to="not-an-email", subject="s", body_text="b")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("bad recipient should raise")
    except ConnectorError as exc:
        assert exc.code == ConnectorErrorCode.BAD_REQUEST.value
    finally:
        loop.close()


def test_taxonomy_429_retryable():
    patcher, _f = _patch([
        _json(200, {"access_token": "AT", "expires_in": 3600}),
        _json(429, {"error": {"message": "slow"}}),
    ])
    try:
        from app.providers.gmail import GmailProviderClient

        async def go():
            await GmailProviderClient().send(CREDS, to="a@b.com", subject="s", body_text="b")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("429 should raise")
        except ConnectorError as exc:
            assert exc.code == ConnectorErrorCode.RATE_LIMITED.value
            assert exc.retryable is True
        finally:
            loop.close()
    finally:
        patcher.stop()


# ----------------------------------------------------------------------
# Full stack
# ----------------------------------------------------------------------

def test_full_stack_gmail_send(client):
    headers = auth_headers(register(client)["token"])
    cred = client.post(
        "/api/credentials",
        json={"name": "Gmail", "type": "gmail", "data": {"oauth": True, "refresh_token": "RT_GMAIL_SECRET_9"}},
        headers=headers,
    ).json()["data"]

    wf = {
        "id": "wf_gmail",
        "name": "Gmail send",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "mail",
                "type": "gmail",
                "parameters": {
                    "operation": "send",
                    "to": "{{ $json.to }}",
                    "subject": "Alert for {{ $json.name }}",
                    "body_text": "Hello {{ $json.name }}",
                },
                "credentials": {"gmail": cred["id"]},
            },
        ],
        "connections": [{"source": "trigger", "target": "mail"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    patcher, fake = _patch([
        _json(200, {"access_token": "AT_FS", "expires_in": 3600}),
        _json(200, {"id": "m_9", "threadId": "t_9"}),
    ])
    try:
        resp = client.post(
            "/api/workflows/wf_gmail/run",
            json={"data": {"to": "ops@x.io", "name": "Ada"}},
            headers=headers,
        )
        eid = resp.json()["data"]["execution_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            data = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
            if data["status"] not in ("running", "queued"):
                break
            time.sleep(0.05)
    finally:
        patcher.stop()

    assert data["status"] == "success", data.get("error")
    out = data["results"]["outputs"]["mail"]["main"][0]
    assert out["sent"] is True and out["id"] == "m_9"
    raw = json.dumps(data, default=str)
    assert "RT_GMAIL_SECRET_9" not in raw


def test_discovery_lists_gmail(client):
    headers = auth_headers(register(client)["token"])
    keys = [c.get("connector_key") or c.get("key") for c in client.get("/api/connectors", headers=headers).json()["data"]]
    assert "gmail" in keys
