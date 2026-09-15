"""Google Calendar provider + full-stack tests (Phase 37).

Provider unit: list/create/update/delete against Calendar v3 with a
scripted HTTP client; refresh-on-401 recovery; error taxonomy; calendar
id sanitization. Full stack: workflow with expressions creates an event
through API -> queue -> worker -> engine -> connector, secret never
leaks into the execution record.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

pytestmark = pytest.mark.timing

from app.config import Settings
from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register


def _settings(**overrides) -> Settings:
    defaults = {"google_client_id": "G_CID", "google_client_secret": "G_SECRET"}
    defaults.update(overrides)
    return Settings(**defaults)


class FakeHTTPClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _json(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_provider_http(responses):
    fake = FakeHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.google_calendar.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


CREDS = {"oauth": True, "refresh_token": "RT_G", "user": "me@gmail.com"}


@pytest.fixture(autouse=True)
def _connectors_and_settings(monkeypatch):
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "G_CID")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "G_SECRET")
    monkeypatch.setattr("app.providers.google_calendar.get_settings", lambda: _settings())
    yield


def test_create_event_refreshes_then_posts():
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_1", "expires_in": 3600}),
        _json(200, {"id": "evt_1", "summary": "Sync"}),
    ])
    try:
        from app.providers.google_calendar import GoogleCalendarProviderClient

        client = GoogleCalendarProviderClient()
        result = asyncio.new_event_loop().run_until_complete(
            client.create_event(CREDS, "primary", {"summary": "Sync"})
        )
    finally:
        patcher.stop()

    assert result["success"] is True and result["id"] == "evt_1"
    m1, u1, k1 = fake.calls[0]
    assert u1 == "https://oauth2.googleapis.com/token"
    m2, u2, k2 = fake.calls[1]
    assert u2.endswith("/calendar/v3/calendars/primary/events")
    assert k2["headers"]["Authorization"] == "Bearer AT_1"


def test_refresh_on_401_recovers():
    """A mid-flight 401 forces one token refresh and retries."""
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_OLD", "expires_in": 3600}),   # initial refresh
        _json(401, {"error": {"message": "expired"}}),                # data call with stale token
        _json(200, {"access_token": "AT_NEW", "expires_in": 3600}),   # forced re-refresh
        _json(200, {"id": "e1", "summary": "Sync"}),                  # retried data call
    ])
    try:
        from app.providers.google_calendar import GoogleCalendarProviderClient

        client = GoogleCalendarProviderClient()
        result = asyncio.new_event_loop().run_until_complete(
            client.get_event(CREDS, "primary", "e1")
        )
    finally:
        patcher.stop()

    assert result["event"]["id"] == "e1"
    # Last data call carried the NEW access token
    m, u, k = fake.calls[-1]
    assert k["headers"]["Authorization"] == "Bearer AT_NEW"
    # Exactly two token endpoint hits
    token_calls = [c for c in fake.calls if c[1].endswith("/token")]
    assert len(token_calls) == 2


def test_error_taxonomy():
    cases = [
        (404, ConnectorErrorCode.NOT_FOUND, False),
        (403, ConnectorErrorCode.FORBIDDEN, False),
        (429, ConnectorErrorCode.RATE_LIMITED, True),
        (500, ConnectorErrorCode.UNAVAILABLE, True),
    ]
    for status_code, expected_code, expected_retryable in cases:
        patcher, _f = _patch_provider_http([
            _json(200, {"access_token": "AT", "expires_in": 3600}),
            _json(status_code, {"error": {"message": "boom"}}),
        ])
        try:
            from app.providers.google_calendar import GoogleCalendarProviderClient

            client = GoogleCalendarProviderClient()

            async def go():
                await client.get_event(CREDS, "primary", "e1")

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(go())
                raise AssertionError(f"{status_code} should have raised")
            except ConnectorError as exc:
                assert exc.code == expected_code.value
                assert exc.retryable is expected_retryable
            finally:
                loop.close()
        finally:
            patcher.stop()


def test_calendar_id_sanitized():
    from app.providers.google_calendar import GoogleCalendarProviderClient

    client = GoogleCalendarProviderClient()

    async def go():
        await client.list_events(CREDS, "../secret")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("traversal should have raised")
    except ConnectorError as exc:
        assert "Invalid calendar id" in str(exc)
    finally:
        loop.close()


# ----------------------------------------------------------------------
# Full stack
# ----------------------------------------------------------------------

GCAL_CREDENTIAL = {"oauth": True, "refresh_token": "G_RT_SUPER_SECRET_77", "user": "me@gmail.com"}


def _setup(client):
    return auth_headers(register(client)["token"])


def test_full_stack_google_calendar_event(client):
    headers = _setup(client)
    cred = client.post(
        "/api/credentials",
        json={"name": "Google Cal", "type": "google_calendar", "data": GCAL_CREDENTIAL},
        headers=headers,
    ).json()["data"]

    wf = {
        "id": "wf_gcal",
        "name": "GCAL create",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "gcal",
                "type": "google_calendar",
                "parameters": {
                    "operation": "create_event",
                    "calendar_id": "primary",
                    "event": {
                        "summary": "{{ $json.title }}",
                        "start": {"date": "{{ $json.day }}"},
                        "end": {"date": "{{ $json.day }}"},
                    },
                },
                "credentials": {"google_calendar": cred["id"]},
            },
        ],
        "connections": [{"source": "trigger", "target": "gcal"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    created = {"id": "evt_9", "summary": "Standup"}
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_FS", "expires_in": 3600}),  # oauth refresh
        _json(200, created),                                        # create event
    ])
    try:
        resp = client.post(
            "/api/workflows/wf_gcal/run", json={"data": {"title": "Standup", "day": "2026-09-01"}},
            headers=headers,
        )
        eid = resp.json()["data"]["execution_id"]
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            data = client.get(f"/api/executions/{eid}", headers=headers).json()["data"]
            if data["status"] not in ("running", "queued"):
                break
            time.sleep(0.05)
    finally:
        patcher.stop()

    assert data["status"] == "success", data.get("error")
    outputs = data["results"]["outputs"]["gcal"]["main"]
    assert outputs[0]["id"] == "evt_9"
    data_calls = [(m, u, k) for (m, u, k) in fake.calls if not u.endswith("/token")]
    assert data_calls, f"expected a data call among {[(u,) for _, u, _ in fake.calls]}"
    m, url, kwargs = data_calls[0]
    assert url.endswith("/calendar/v3/calendars/primary/events")
    assert kwargs["json"]["summary"] == "Standup"
    raw = json.dumps(data, default=str)
    assert "G_RT_SUPER_SECRET_77" not in raw


def test_discovery_lists_google_calendar(client):
    headers = _setup(client)
    body = client.get("/api/connectors", headers=headers).json()["data"]
    keys = [c.get("connector_key") or c.get("key") for c in body]
    assert "google_calendar" in keys
