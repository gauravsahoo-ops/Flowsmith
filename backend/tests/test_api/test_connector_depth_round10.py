"""Depth pass 10: OpenAI, Anthropic, Pinecone, Twilio, WhatsApp, and Sentry."""

from __future__ import annotations

import pytest

from app.connectors import ensure_builtin_connectors, get_registry
from tests.test_api._connector_fakes import json_response, patch_provider_http


class _FakeResponse:
    def __init__(self, payload=None, headers=None) -> None:
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _FakeHttpxClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    def _next(self, method: str, url: str, **kwargs) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    async def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)

    async def put(self, url, **kwargs):
        return self._next("PUT", url, **kwargs)


@pytest.fixture(autouse=True)
def _connectors():
    ensure_builtin_connectors()


@pytest.mark.asyncio
async def test_openai_image_and_files(monkeypatch):
    from app.providers.openai import OpenAIProviderClient

    client = OpenAIProviderClient()
    posted = []

    async def fake_post(creds, path, body, what, timeout=60.0):
        posted.append((path, body))
        return {"data": [{"url": "https://img.test/1.png"}]}

    monkeypatch.setattr(client, "_post", fake_post)
    image = await client.create_image({"api_key": "x"}, "A red fox", size="512x512")
    assert image["data"][0]["url"].endswith("1.png")
    assert posted[0][1]["size"] == "512x512"

    patcher, fake = patch_provider_http("app.providers.openai", [
        json_response(200, {"data": [{"id": "file_1"}]}),
    ])
    try:
        files = await client.list_files({"api_key": "x"}, purpose="assistants")
    finally:
        patcher.stop()
    assert files["data"][0]["id"] == "file_1"
    assert fake.calls[0][2]["params"] == {"purpose": "assistants"}


@pytest.mark.asyncio
async def test_anthropic_list_and_get_model(monkeypatch):
    from app.providers.anthropic import AnthropicProviderClient

    client = AnthropicProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path))
        if path == "models":
            return {"data": [{"id": "claude-3-5-sonnet"}]}
        return {"id": "claude-3-5-sonnet"}

    monkeypatch.setattr(client, "request_anthropic", fake_request)
    models = await client.list_models({"api_key": "x"})
    assert models["data"][0]["id"].startswith("claude")
    model = await client.get_model({"api_key": "x"}, "claude-3-5-sonnet")
    assert model["id"] == "claude-3-5-sonnet"
    assert calls == [("GET", "models"), ("GET", "models/claude-3-5-sonnet")]


@pytest.mark.asyncio
async def test_pinecone_list_and_delete_vectors(monkeypatch):
    from app.connectors import pinecone_connector as module

    fake = _FakeHttpxClient([
        _FakeResponse({"indexes": [{"name": "docs"}]}),
        _FakeResponse({}),
    ])
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: fake)

    async def fake_assert(url: str, node_id: str = "") -> None:
        return None

    monkeypatch.setattr("app.security.ssrf.assert_public_url", fake_assert)
    conn = module.PineconeConnector()
    context = {"credentials": {"pinecone": {"api_key": "key", "host": "docs.svc.pinecone.io"}}}

    indexes = await conn.op_execute("list_indexes", {}, context)
    assert indexes["indexes"][0]["name"] == "docs"

    deleted = await conn.op_execute(
        "delete_vectors", {"ids": ["v1"], "namespace": "demo"}, context,
    )
    assert deleted == {}
    assert fake.calls[-1][1].endswith("/vectors/delete")


@pytest.mark.asyncio
async def test_twilio_calls_and_account(monkeypatch):
    from app.providers.twilio import TwilioProviderClient

    client = TwilioProviderClient()
    calls = []

    async def fake_request(method, path, creds, **kwargs):
        calls.append((method, path, kwargs))
        if "Calls" in path:
            return {"calls": [{"sid": "CA1"}]}
        return {"sid": "AC1", "friendly_name": "Acme"}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"account_sid": "AC1", "auth_token": "token"}

    call_list = await client.list_calls(creds, limit=5)
    assert call_list[0]["sid"] == "CA1"

    account = await client.get_account(creds)
    assert account["friendly_name"] == "Acme"
    assert calls[-1][1] == ".json"


@pytest.mark.asyncio
async def test_whatsapp_media_and_read(monkeypatch):
    from app.providers.whatsapp import WhatsAppProviderClient

    client = WhatsAppProviderClient()
    calls = []

    async def fake_post(creds, body, what, timeout=30.0):
        calls.append((what, body))
        return {"messages": [{"id": "wamid.1"}]}

    monkeypatch.setattr(client, "_post_message", fake_post)
    creds = {"access_token": "token", "phone_number_id": "123"}

    media = await client.send_media(
        creds, "15551234567", "image", "https://example.com/a.png", caption="Hi",
    )
    assert media["messages"][0]["id"] == "wamid.1"
    assert calls[0][1]["image"]["caption"] == "Hi"

    read = await client.mark_read(creds, "wamid.1")
    assert read["messages"][0]["id"] == "wamid.1"
    assert calls[-1][1] == {"status": "read", "message_id": "wamid.1"}


@pytest.mark.asyncio
async def test_sentry_projects_and_events(monkeypatch):
    from app.connectors import sentry_connector as module

    fake = _FakeHttpxClient([
        _FakeResponse([{"slug": "api"}]),
        _FakeResponse([{"eventID": "e1"}]),
    ])
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: fake)
    conn = module.SentryConnector()
    context = {"credentials": {"sentry": {
        "auth_token": "token", "organization_slug": "acme",
    }}}

    projects = await conn.op_execute("list_projects", {}, context)
    assert projects["projects"][0]["slug"] == "api"

    events = await conn.op_execute("list_events", {"issue_id": "42"}, context)
    assert events["events"][0]["eventID"] == "e1"


def test_depth_round10_definitions_expose_new_operations():
    expected = {
        "openai": {"create_image", "list_files"},
        "anthropic": {"list_models", "get_model"},
        "pinecone": {"list_indexes", "delete_vectors"},
        "twilio": {"list_calls", "get_account"},
        "whatsapp": {"send_media", "mark_read"},
        "sentry": {"list_projects", "list_events"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
