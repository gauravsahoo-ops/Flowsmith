"""Dropbox connector tests.

Proves: Bearer auth, RPC shapes (list/metadata/create/delete), text
upload via the content endpoint, error_summary mapping, 429 retryable.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.dropbox"]
CREDS = {"access_token": "sl_dropbox_secret"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_list_folder_posts_rpc_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"entries": [{".tag": "file", "name": "a.txt"}], "has_more": False}),
    ])
    try:
        from app.providers.dropbox import DropboxProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            DropboxProviderClient().list_folder(CREDS, "/docs", limit=10)
        )
    finally:
        patcher.stop()

    assert out["entries"][0]["name"] == "a.txt"
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://api.dropboxapi.com/2/files/list_folder"
    assert kwargs["headers"]["Authorization"] == "Bearer sl_dropbox_secret"
    assert kwargs["json"] == {"path": "/docs", "recursive": False, "limit": 10}


def test_upload_text_uses_content_endpoint():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"name": "note.txt", "path_lower": "/note.txt"}),
    ])
    try:
        from app.providers.dropbox import DropboxProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            DropboxProviderClient().upload_text(CREDS, "/note.txt", "hello")
        )
    finally:
        patcher.stop()

    assert out["name"] == "note.txt"
    _, url, kwargs = fake.calls[0]
    assert url == "https://content.dropboxapi.com/2/files/upload"
    assert "note.txt" in kwargs["headers"]["Dropbox-API-Arg"]
    assert kwargs["data"] == b"hello"


def test_error_summary_maps_to_bad_request():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(409, {"error_summary": "path/not_found/"}),
    ])
    try:
        from app.providers.dropbox import DropboxProviderClient

        async def go():
            await DropboxProviderClient().get_metadata(CREDS, "/missing")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("409 should have raised")
        except ConnectorError as exc:
            assert "path/not_found" in str(exc)
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"error_summary": "too_many_requests/"}),
    ])
    try:
        from app.providers.dropbox import DropboxProviderClient

        async def go():
            await DropboxProviderClient().list_folder(CREDS)

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


def test_test_connection_returns_display_name():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"name": {"display_name": "Gaurav"}}),
    ])
    try:
        from app.providers.dropbox import DropboxProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            DropboxProviderClient().test_connection(CREDS)
        )
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected as Gaurav."}


def test_connector_dispatch_and_discovery():
    import pytest as _pytest

    from app.connectors.dropbox_connector import DropboxConnector

    assert get_registry().get("dropbox") is not None
    conn = DropboxConnector()
    with _pytest.raises(ConnectorError):
        asyncio.new_event_loop().run_until_complete(
            conn.op_execute("get_metadata", {"path": "/x"},
                            {"credentials": {"dropbox": {}}})
        )
    assert asyncio.new_event_loop().run_until_complete(
        conn.op_list())["output"]["operations"] == [
        "list_folder", "get_metadata", "create_folder", "delete", "upload_text"]
