"""Notion connector tests (Phase 11 business connectors).

Proves: Notion-Version header + integration token, start_cursor
pagination on query_database, create/update validation, 401 taxonomy.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.base"]
CREDS = {"integration_token": "ntn_secret_token_value"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_query_database_paginates_and_summarizes():
    page1 = {
        "results": [{
            "id": "page-1", "url": "https://notion.so/page-1",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "First"}]},
                "Status": {"type": "status", "status": {"name": "In progress"}},
                "Points": {"type": "number", "number": 3},
            },
        }],
        "has_more": True,
        "next_cursor": "CUR_2",
    }
    page2 = {"results": [], "has_more": False}
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, page1),
        json_response(200, page2),
    ])
    try:
        from app.providers.notion import NotionProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            NotionProviderClient().query_database(
                CREDS, "a1b2c3d4e5f6a7b8c9d0e5f6a7b8c9d0", max_pages=3,
            )
        )
    finally:
        patcher.stop()

    assert out["count"] == 1 and out["has_more"] is False
    props = out["pages"][0]["properties"]
    assert props["Name"] == "First"
    assert props["Status"] == "In progress"
    assert props["Points"] == 3

    method, url, kwargs = fake.calls[0]
    assert url == "https://api.notion.com/v1/databases/a1b2c3d4e5f6a7b8c9d0e5f6a7b8c9d0/query"
    assert kwargs["headers"]["Notion-Version"] == "2022-06-28"
    assert kwargs["headers"]["Authorization"] == f"Bearer {CREDS['integration_token']}"
    _, _, kwargs2 = fake.calls[1]
    assert kwargs2["json"]["start_cursor"] == "CUR_2"


def test_create_page_requires_properties():
    from app.providers.notion import NotionProviderClient

    async def go():
        await NotionProviderClient().create_page(CREDS, "a1b2c3d4e5f6a7b8c9d0e5f6a7b8c9d0", {})

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("empty properties should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
    finally:
        loop.close()


def test_invalid_database_id_rejected():
    from app.providers.notion import NotionProviderClient

    async def go():
        await NotionProviderClient().query_database(CREDS, "../../etc")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("bad database id should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        assert "Invalid" in str(exc)
    finally:
        loop.close()


def test_unauthorized_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, {"message": "API token is invalid."}),
    ])
    try:
        from app.providers.notion import NotionProviderClient

        async def go():
            await NotionProviderClient().query_database(CREDS, "a1b2c3d4e5f6a7b8c9d0e5f6a7b8c9d0")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("401 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)
        finally:
            loop.close()
    finally:
        patcher.stop()
