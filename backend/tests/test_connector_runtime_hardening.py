"""Connector runtime edge-case regression tests.

These are intentionally network-free: they cover host substitution,
path/query separation, credential completeness, and retry-header parsing
without claiming live vendor certification.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode
from app.connectors.http_connector import retry_delay_seconds
from app.connectors.vendor_rest import VENDOR_SPECS, VendorRESTConnector


class FakeResponse:
    def __init__(self, status_code: int = 200, body: str = "{}", headers=None):
        self.status_code = status_code
        self.text = body
        self.headers = headers or {}

    def json(self):
        return {"ok": True}


def _creds(spec) -> dict:
    return {field: "test-token" for field in spec.credential_fields}


@pytest.mark.asyncio
async def test_vendor_rejects_host_override_in_template_value():
    spec = VENDOR_SPECS["freshservice"]
    connector = VendorRESTConnector(spec)
    with pytest.raises(ConnectorError) as exc_info:
        await connector.op_execute(
            "list_tickets",
            {"params": {"domain": "evil.example/redirect"}},
            {"credentials": {spec.key: _creds(spec)}},
        )
    assert exc_info.value.code == ConnectorErrorCode.BAD_REQUEST.value
    assert "invalid host" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_vendor_retry_after_is_sanitized():
    spec = VENDOR_SPECS["circle_ci"]
    connector = VendorRESTConnector(spec)
    client = AsyncMock()
    with patch("app.security.safe_http_client.get_safe_http_client", return_value=client):
        client.request.return_value = FakeResponse(
            status_code=429, headers={"Retry-After": "2.5"}
        )
        with pytest.raises(ConnectorError) as numeric:
            await connector.op_execute(
                "get_user", {}, {"credentials": {spec.key: _creds(spec)}}
            )
        assert numeric.value.retry_after == 2.5

        client.request.return_value = FakeResponse(
            status_code=429, headers={"Retry-After": "not-a-number"}
        )
        with pytest.raises(ConnectorError) as malformed:
            await connector.op_execute(
                "get_user", {}, {"credentials": {spec.key: _creds(spec)}}
            )
        assert malformed.value.retry_after is None


@pytest.mark.asyncio
async def test_vendor_requires_all_declared_credentials_for_connect():
    spec = VENDOR_SPECS["confluence"]  # email + api_token
    connector = VendorRESTConnector(spec)
    assert await connector.connect({"email": "user@example.com"}) is False
    assert await connector.connect(
        {"email": "user@example.com", "api_token": "secret"}
    ) is True


def test_http_retry_delay_header_is_bounded_and_safe():
    assert retry_delay_seconds(SimpleNamespace(headers={"Retry-After": "2.5"}), 1) == 2.5
    assert retry_delay_seconds(SimpleNamespace(headers={"Retry-After": "999"}), 1) == 5.0
    assert retry_delay_seconds(
        SimpleNamespace(headers={"Retry-After": "not-a-date"}), 1.5
    ) == 1.5
    assert retry_delay_seconds(None, -10) == 0.0


def test_http_connector_pagination_is_bounded_by_schema():
    from app.connectors.http_connector import HTTPConnectorParams

    with pytest.raises(Exception):
        HTTPConnectorParams(url="https://example.com", page_size=0)
    with pytest.raises(Exception):
        HTTPConnectorParams(url="https://example.com", max_pages=10_000)
    with pytest.raises(Exception):
        HTTPConnectorParams(url="https://example.com", retry_delay_seconds=-1)
