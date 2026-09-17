"""OpenAI connector tests.

Proves: Bearer auth, embedding/chat payload shapes, OpenAI error object
mapping (invalid key -> AUTH_FAILED), 429 retryable, model-catalog probe.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.openai"]
CREDS = {"api_key": "sk-test-secret"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_create_embedding_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"data": [{"embedding": [0.1, 0.2], "index": 0}]}),
    ])
    try:
        from app.providers.openai import OpenAIProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            OpenAIProviderClient().create_embedding(CREDS, "text-embedding-3-small", "hello")
        )
    finally:
        patcher.stop()

    assert out["data"][0]["embedding"] == [0.1, 0.2]
    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://api.openai.com/v1/embeddings"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test-secret"
    assert kwargs["json"] == {"model": "text-embedding-3-small", "input": "hello"}


def test_chat_completion_posts_shape():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, {"choices": [{"message": {"content": "hi"}}]}),
    ])
    try:
        from app.providers.openai import OpenAIProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            OpenAIProviderClient().chat_completion(
                CREDS, "gpt-4o-mini", [{"role": "user", "content": "hi"}])
        )
    finally:
        patcher.stop()

    assert out["choices"][0]["message"]["content"] == "hi"
    _, url, kwargs = fake.calls[0]
    assert url == "https://api.openai.com/v1/chat/completions"
    assert kwargs["json"]["model"] == "gpt-4o-mini"


def test_invalid_key_maps_to_auth_failed():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(401, {"error": {"message": "Incorrect API key provided.", "type": "invalid_request_error"}}),
    ])
    try:
        from app.providers.openai import OpenAIProviderClient

        async def go():
            await OpenAIProviderClient().list_models({"api_key": "BAD"})

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("401 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.AUTH_FAILED, ConnectorErrorCode.AUTH_FAILED.value)
            assert "Incorrect API key" in str(exc)
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_rate_limited_is_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(429, {"error": {"message": "Rate limit reached."}}),
    ])
    try:
        from app.providers.openai import OpenAIProviderClient

        async def go():
            await OpenAIProviderClient().list_models(CREDS)

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


def test_test_connection_counts_models():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(200, {"data": [{"id": "gpt-4o"}, {"id": "o1"}]}),
    ])
    try:
        from app.providers.openai import OpenAIProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            OpenAIProviderClient().test_connection(CREDS)
        )
    finally:
        patcher.stop()

    assert out == {"ok": True, "message": "Connected (2 models available)."}


def test_connector_dispatch_and_discovery():
    import pytest as _pytest

    from app.connectors.openai_connector import OpenAIConnector

    assert get_registry().get("openai") is not None
    conn = OpenAIConnector()
    with _pytest.raises(ConnectorError):
        asyncio.new_event_loop().run_until_complete(
            conn.op_execute("list_models", {}, {"credentials": {"openai": {}}})
        )
    assert asyncio.new_event_loop().run_until_complete(
        conn.op_list())["output"]["operations"] == [
        "list_models", "create_embedding", "chat_completion"]
