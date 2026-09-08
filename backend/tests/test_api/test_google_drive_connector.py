"""Google Drive connector tests (Phase 11 business connectors).

Proves: OAuth authorize URL carries the Drive scope, refresh-token mint
against the shared Google app, nextPageToken pagination, multipart upload
shape, error taxonomy and discovery.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http
from tests.test_api.conftest import auth_headers, register

MODULE = ["app.providers.base", "app.security.safe_http_client"]


def _settings(**overrides) -> Settings:
    defaults = {
        "google_client_id": "G_CID",
        "google_client_secret": "G_SECRET",
        "google_redirect_uri": "http://127.0.0.1:5173/callback",
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture(autouse=True)
def _connectors_and_settings(monkeypatch):
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    monkeypatch.setattr("app.providers.google_drive._get_settings", lambda: _settings())
    yield


CREDS = {"oauth": True, "refresh_token": "RT_DRIVE"}


def test_authorize_url_requests_drive_scope():
    from app.oauth_providers import GOOGLE_DRIVE

    url = GOOGLE_DRIVE.authorize_url(
        _settings(), state="st", challenge="ch", login_url=""
    )
    assert "accounts.google.com" in url
    assert "https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive" in url  # url-encoded scope
    assert "access_type=offline" in url


def test_list_files_refreshes_token_and_paginates():
    page1 = {
        "nextPageToken": "TOK2",
        "files": [{"id": "f1", "name": "a.csv"}],
    }
    page2 = {"files": [{"id": "f2", "name": "b.csv"}]}
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"access_token": "AT_1", "expires_in": 1800}),
        json_response(200, page1),
        json_response(200, page2),
    ])
    try:
        from app.providers.google_drive import GoogleDriveProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            GoogleDriveProviderClient().list_files(CREDS, max_pages=3)
        )
    finally:
        patcher.stop()

    assert [f["id"] for f in out["files"]] == ["f1", "f2"]
    assert out["has_more"] is False
    # Token mint happened first against the shared Google app…
    method0, url0, kwargs0 = fake.calls[0]
    assert url0 == "https://oauth2.googleapis.com/token"
    assert "client_secret=G_SECRET" in kwargs0["data"]
    # …then the files endpoint with the bearer token and page cursor.
    method1, url1, kwargs1 = fake.calls[1]
    assert url1.startswith("https://www.googleapis.com/drive/v3/files")
    assert kwargs1["headers"]["Authorization"] == "Bearer AT_1"
    assert "pageToken" not in (kwargs1.get("params") or {})
    _, _, kwargs2 = fake.calls[2]
    assert kwargs2["params"]["pageToken"] == "TOK2"


def test_upload_file_sends_multipart_with_metadata():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"id": "newfile1", "name": "report.csv"}),
    ])
    try:
        from app.providers.google_drive import GoogleDriveProviderClient

        client = GoogleDriveProviderClient()
        patcher2 = patch.object(
            GoogleDriveProviderClient, "_get_access_token",
            new=AsyncMock(return_value="AT_STATIC"),
        )
        patcher2.start()
        try:
            out = asyncio.new_event_loop().run_until_complete(
                client.upload_file(CREDS, "report.csv", "a,b\n1,2\n", mime_type="text/csv")
            )
        finally:
            patcher2.stop()
    finally:
        patcher.stop()

    assert out == {"file_id": "newfile1", "name": "report.csv", "success": True}
    method, url, kwargs = fake.calls[0]
    assert url == "https://www.googleapis.com/upload/drive/v3/files"
    body: bytes = kwargs["data"]
    assert b'"name": "report.csv"' in body
    assert b"a,b\n1,2\n" in body
    assert kwargs["headers"]["Content-Type"].startswith("multipart/related; boundary=")


def test_error_taxonomy_404_not_found():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"access_token": "AT", "expires_in": 1800}),
        json_response(404, {"error": {"message": "File not found"}}),
    ])
    try:
        from app.providers.google_drive import GoogleDriveProviderClient

        async def go():
            await GoogleDriveProviderClient().get_file(CREDS, "missing")

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


def test_discovery_lists_google_drive(client):
    headers = auth_headers(register(client)["token"])
    body = client.get("/api/connectors", headers=headers).json()["data"]
    keys = {c.get("connector_key") or c.get("key") for c in body}
    assert "google_drive" in keys
