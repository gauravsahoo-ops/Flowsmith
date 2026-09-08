"""Airtable connector tests (Phase 11 business connectors).

Proves: personal-access-token bearer auth, offset pagination, base/record
id validation, fields-map validation.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.base"]
CREDS = {"personal_access_token": "pat_secret_value"}
BASE = "appTestBase123456"


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_list_records_paginates_with_offset():
    page1 = {
        "records": [{"id": "rec1", "fields": {"Name": "A"}}],
        "offset": "OFF2",
    }
    page2 = {"records": [{"id": "rec2", "fields": {"Name": "B"}}]}
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, page1),
        json_response(200, page2),
    ])
    try:
        from app.providers.airtable import AirtableProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            AirtableProviderClient().list_records(CREDS, BASE, "Tasks", max_pages=3)
        )
    finally:
        patcher.stop()

    assert [r["id"] for r in out["records"]] == ["rec1", "rec2"]
    method, url, kwargs = fake.calls[0]
    assert url == f"https://api.airtable.com/v0/{BASE}/Tasks"
    assert kwargs["headers"]["Authorization"] == "Bearer pat_secret_value"
    _, _, kwargs2 = fake.calls[1]
    assert kwargs2["params"]["offset"] == "OFF2"


def test_list_records_passes_formula_and_view():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"records": []}),
    ])
    try:
        from app.providers.airtable import AirtableProviderClient

        asyncio.new_event_loop().run_until_complete(
            AirtableProviderClient().list_records(
                CREDS, BASE, "Tasks", view="Open", filter_by_formula="{Status} = 'Open'",
            )
        )
    finally:
        patcher.stop()

    _, _, kwargs = fake.calls[0]
    assert kwargs["params"]["view"] == "Open"
    assert kwargs["params"]["filterByFormula"] == "{Status} = 'Open'"


def test_bad_base_id_rejected():
    from app.providers.airtable import AirtableProviderClient

    async def go():
        await AirtableProviderClient().list_records(CREDS, "../evil", "Tasks")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("bad base id should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        assert "app" in str(exc)
    finally:
        loop.close()


def test_create_record_requires_fields():
    from app.providers.airtable import AirtableProviderClient

    async def go():
        await AirtableProviderClient().create_record(CREDS, BASE, "Tasks", {})

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("empty fields should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
    finally:
        loop.close()


def test_table_name_is_url_encoded():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"records": []}),
    ])
    try:
        from app.providers.airtable import AirtableProviderClient

        asyncio.new_event_loop().run_until_complete(
            AirtableProviderClient().list_records(CREDS, BASE, "My Table Name")
        )
    finally:
        patcher.stop()

    _, url, _kwargs = fake.calls[0]
    assert "/My%20Table%20Name" in url
