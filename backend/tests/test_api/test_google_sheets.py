"""Google Sheets connector tests (Phase 39).

OAuth reuses the shared Google app (config_prefix=google) with a sheets
scope set; provider covers read/append/update + taxonomy; full stack
runs an append through queue/engine with expressions and secret-leak
check.
"""

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


CREDS = {"oauth": True, "refresh_token": "RT_S", "user": "me@gmail.com"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    r = get_registry()
    r.initialize()
    register_builtin_connectors()
    monkeypatch.setattr("app.providers.google_sheets._get_settings", lambda: _settings())
    yield


def test_append_row_refreshes_then_posts():
    patcher, fake = _patch([
        _json(200, {"access_token": "AT", "expires_in": 3600}),
        _json(200, {"updates": {"updatedCells": 3, "updatedRange": "Sheet1!A5:C5"}}),
    ])
    try:
        from app.providers.google_sheets import GoogleSheetsProviderClient

        result = asyncio.new_event_loop().run_until_complete(
            GoogleSheetsProviderClient().append_row(CREDS, "ssid123", "Sheet1!A:C", ["a", 1, True])
        )
    finally:
        patcher.stop()

    assert result["appended"] is True
    m2, u2, k2 = fake.calls[1]
    assert ":append" in u2
    assert k2["json"]["values"] == [["a", 1, True]]
    assert k2["params"]["valueInputOption"] == "USER_ENTERED"


def test_read_maps_rows():
    patcher, fake = _patch([
        _json(200, {"access_token": "AT", "expires_in": 3600}),
        _json(200, {"values": [["n", "e"], ["Ada", "a@b.com"]], "range": "Sheet1!A1:B2"}),
    ])
    try:
        from app.providers.google_sheets import GoogleSheetsProviderClient

        result = asyncio.new_event_loop().run_until_complete(
            GoogleSheetsProviderClient().read_values(CREDS, "ssid123", "Sheet1!A1:B100")
        )
    finally:
        patcher.stop()

    assert result["count"] == 2 and result["rows"][1] == ["Ada", "a@b.com"]


def test_taxonomy_and_bad_spreadsheet_id():
    for status_code, expected_code, retryable in ((403, ConnectorErrorCode.FORBIDDEN, False), (429, ConnectorErrorCode.RATE_LIMITED, True)):
        patcher, _f = _patch([
            _json(200, {"access_token": "AT", "expires_in": 3600}),
            _json(status_code, {"error": {"message": "no"}}),
        ])
        try:
            from app.providers.google_sheets import GoogleSheetsProviderClient

            async def go():
                await GoogleSheetsProviderClient().read_values(CREDS, "ssid", "Sheet1!A1")

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(go())
                raise AssertionError(f"{status_code} should raise")
            except ConnectorError as exc:
                assert exc.code == expected_code.value and exc.retryable is retryable
            finally:
                loop.close()
        finally:
            patcher.stop()

    from app.providers.google_sheets import GoogleSheetsProviderClient

    async def bad():
        await GoogleSheetsProviderClient().read_values(CREDS, "../x", "Sheet1!A1")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(bad())
        raise AssertionError("bad id should raise")
    except ConnectorError as exc:
        assert "Invalid spreadsheet id" in str(exc)
    finally:
        loop.close()


# ----------------------------------------------------------------------
# Full stack
# ----------------------------------------------------------------------

SHEETS_CRED = {"oauth": True, "refresh_token": "S_RT_SECRET_42", "user": "me@gmail.com"}


def test_full_stack_google_sheets_append(client):
    headers = auth_headers(register(client)["token"])
    cred = client.post(
        "/api/credentials",
        json={"name": "Sheets", "type": "google_sheets", "data": SHEETS_CRED},
        headers=headers,
    ).json()["data"]

    wf = {
        "id": "wf_gsheets",
        "name": "GS append",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "sheet",
                "type": "google_sheets",
                "parameters": {
                    "operation": "append",
                    "spreadsheet_id": "ssidABC123",
                    "range": "Sheet1!A:C",
                    "values": ["{{ $json.name }}", "{{ $json.email }}", "{{ $now }}"],
                },
                "credentials": {"google_sheets": cred["id"]},
            },
        ],
        "connections": [{"source": "trigger", "target": "sheet"}],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    patcher, fake = _patch([
        _json(200, {"access_token": "AT_FS", "expires_in": 3600}),
        _json(200, {"updates": {"updatedCells": 3, "updatedRange": "Sheet1!A9:C9"}}),
    ])
    try:
        resp = client.post("/api/workflows/wf_gsheets/run", json={"data": {"name": "Ada", "email": "ada@b.io"}}, headers=headers)
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
    data_calls = [(m, u, k) for (m, u, k) in fake.calls if not u.endswith("/token")]
    assert data_calls and ":append" in data_calls[0][1]
    row = data_calls[0][2]["json"]["values"][0]
    assert row[0] == "Ada" and row[1] == "ada@b.io"  # expression-resolved
    raw = json.dumps(data, default=str)
    assert "S_RT_SECRET_42" not in raw


def test_discovery_lists_google_sheets(client):
    headers = auth_headers(register(client)["token"])
    keys = [c.get("connector_key") or c.get("key") for c in client.get("/api/connectors", headers=headers).json()["data"]]
    assert "google_sheets" in keys
