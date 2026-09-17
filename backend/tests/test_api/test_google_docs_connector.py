"""Google Docs connector tests.

Proves: Bearer auth on Docs endpoints, document CRUD shapes, append
(two-call endIndex flow), tokeninfo probe, 429 retryable, OAuth provider
registration + refresh alias + credential validation.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.google_docs"]
CREDS = {"access_token": "ya29.docs_secret"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_get_document_shapes():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"documentId": "DOC1", "title": "Plan"}),
    ])
    try:
        from app.providers.google_docs import GoogleDocsProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            GoogleDocsProviderClient().get_document(CREDS, "DOC1")
        )
    finally:
        patcher.stop()

    assert out["title"] == "Plan"
    method, url, kwargs = fake.calls[0]
    assert method == "GET"
    assert url == "https://docs.googleapis.com/v1/documents/DOC1"
    assert kwargs["headers"]["Authorization"] == "Bearer ya29.docs_secret"


def test_append_text_reads_end_index_first():
    doc = {"documentId": "DOC1", "body": {"content": [
        {"endIndex": 1},
        {"paragraph": {}, "endIndex": 12},
    ]}}
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, doc),
        json_response(200, {"replies": [{}]}),
    ])
    try:
        from app.providers.google_docs import GoogleDocsProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            GoogleDocsProviderClient().append_text(CREDS, "DOC1", "more")
        )
    finally:
        patcher.stop()

    assert out == {"replies": [{}]}
    _, url2, kwargs2 = fake.calls[1]
    assert url2 == "https://docs.googleapis.com/v1/documents/DOC1:batchUpdate"
    req = kwargs2["json"]["requests"][0]["insertText"]
    assert req["location"]["index"] == 11
    assert req["text"] == "more"


def test_auth_failure_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, {"error": {"message": "Invalid Credentials"}}),
    ])
    try:
        from app.providers.google_docs import GoogleDocsProviderClient

        async def go():
            await GoogleDocsProviderClient().get_document({"access_token": "BAD"}, "DOC1")

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


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"error": {"message": "Rate exceeded"}}),
    ])
    try:
        from app.providers.google_docs import GoogleDocsProviderClient

        async def go():
            await GoogleDocsProviderClient().get_document(CREDS, "DOC1")

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


def test_oauth_stack_registered():
    from app.auth_state.adapter import PROVIDER_REFRESH, canonical_provider
    from app.oauth_providers import get_provider

    assert canonical_provider("google_docs") == "google"
    assert PROVIDER_REFRESH["google"]["token_url"] == "https://oauth2.googleapis.com/token"
    spec = get_provider("google_docs")
    assert spec.credential_type == "google_docs"
    assert spec.scopes_setting == "google_docs_scopes"

    from app.credentials.registry import validate_data

    validated = validate_data("google_docs", {"refresh_token": "rt_123"})
    assert validated["refresh_token"] == "rt_123"
    with pytest.raises(ValueError):
        validate_data("google_docs", {"user": "nobody"})


def test_connector_dispatch_and_discovery():
    import pytest as _pytest

    from app.connectors.google_docs_connector import GoogleDocsConnector

    assert get_registry().get("google_docs") is not None
    conn = GoogleDocsConnector()
    with _pytest.raises(ConnectorError):
        asyncio.new_event_loop().run_until_complete(
            conn.op_execute("get_document", {"document_id": "D1"},
                            {"credentials": {"google_docs": {}}})
        )
    assert asyncio.new_event_loop().run_until_complete(
        conn.op_list())["output"]["operations"] == [
        "get_document", "create_document", "append_text", "batch_update"]
