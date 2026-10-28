"""Regression tests for DB-bound OAuth app credentials on provider refresh."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.providers.base import BaseProviderClient
from app.providers.google_sheets import GoogleSheetsProviderClient
from app.providers.hubspot import HubSpotProviderClient


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        return httpx.Response(
            200,
            json={"access_token": "refreshed-token", "expires_in": 3600},
            request=httpx.Request(method, url),
        )


@pytest.mark.asyncio
async def test_hubspot_refresh_prefers_bound_app_credentials(monkeypatch):
    fake = FakeHTTPClient()
    monkeypatch.setattr("app.providers.hubspot.get_safe_http_client", lambda: fake)

    token, _expires_at = await HubSpotProviderClient()._refresh_access_token(
        "refresh-token", "BOUND_CID", "BOUND_SECRET"
    )

    assert token == "refreshed-token"
    body = fake.calls[0][2]["data"]
    assert "client_id=BOUND_CID" in body
    assert "client_secret=BOUND_SECRET" in body


@pytest.mark.asyncio
async def test_base_provider_refresh_prefers_bound_app_credentials(monkeypatch):
    fake = FakeHTTPClient()
    monkeypatch.setattr("app.providers.base.get_safe_http_client", lambda: fake)

    token = await GoogleSheetsProviderClient()._get_access_token({
        "refresh_token": "refresh-token",
        "client_id": "BOUND_CID",
        "client_secret": "BOUND_SECRET",
    })

    assert token == "refreshed-token"
    body = fake.calls[0][2]["data"]
    assert "client_id=BOUND_CID" in body
    assert "client_secret=BOUND_SECRET" in body


def test_base_provider_exposes_credential_override():
    """The shared helper must not silently drop explicit app credentials."""
    class _Provider(BaseProviderClient):
        def _client_id_secret(self) -> tuple[str, str]:
            return "ENV_CID", "ENV_SECRET"

        async def _refresh(self, http_client, refresh_token):
            raise NotImplementedError

    provider = _Provider()
    assert provider._resolve_client_id_secret(
        {"client_id": "BOUND_CID", "client_secret": "BOUND_SECRET"}
    ) == ("BOUND_CID", "BOUND_SECRET")
    assert provider._resolve_client_id_secret({}) == ("ENV_CID", "ENV_SECRET")
