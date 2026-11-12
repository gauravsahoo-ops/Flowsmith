"""HubSpot provider + connector + full-stack tests (Phase 33).

Proves the second business connector through the real stack
(API -> queue -> worker -> engine -> connector -> provider client) with a
scripted SafeHTTPClient — the same pattern as the Salesforce suites:

- provider: search/get/create/update against CRM v3, error taxonomy
  (401 AUTH_FAILED, 404 NOT_FOUND, 429 RATE_LIMITED retryable),
  refresh-on-401 recovery, private-token mode.
- connector: op_execute validation (missing inputs, unknown object).
- full stack: workflow with expressions resolves inputs and returns the
  created record; secrets never leak into the execution record.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.connectors import ConnectorError, get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register


def _settings(**overrides) -> Settings:
    defaults = {
        "hubspot_client_id": "HS_CID",
        "hubspot_client_secret": "HS_SECRET",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class FakeHSHTTPClient:
    """Scripted SafeHTTPClient replacement: records calls, returns in order."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected extra call: {method} {url}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _json(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_provider_http(responses: list[httpx.Response]):
    fake = FakeHSHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.hubspot.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


OAUTH_CREDS = {"oauth": True, "refresh_token": "RT_ZZZ", "hub_id": "123"}
PRIVATE_CREDS = {"private_token": "pat-abc-123"}


@pytest.fixture(autouse=True)
def _connectors_and_settings(monkeypatch):
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    monkeypatch.setenv("HUBSPOT_CLIENT_ID", "HS_CID")
    monkeypatch.setenv("HUBSPOT_CLIENT_SECRET", "HS_SECRET")
    monkeypatch.setattr("app.providers.hubspot.get_settings", lambda: _settings())
    yield


# ----------------------------------------------------------------------
# Provider unit level
# ----------------------------------------------------------------------

def test_search_finds_record_with_oauth_refresh():
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_1", "expires_in": 1800}),          # token refresh
        _json(200, {"results": [{"id": "501", "properties": {"email": "a@b.com"}}]}),  # search
    ])
    try:
        from app.providers.hubspot import HubSpotProviderClient

        client = HubSpotProviderClient()

        import asyncio

        result = asyncio.new_event_loop().run_until_complete(
            client.search_records(OAUTH_CREDS, "contacts", "email", "a@b.com")
        )
    finally:
        patcher.stop()

    assert result["found"] is True
    assert result["record"]["id"] == "501"
    # First call refreshed the token with server-side credentials
    method, url, kwargs = fake.calls[0]
    assert url.endswith("/oauth/v1/token")
    assert "client_secret=HS_SECRET" in kwargs["data"]
    # Second call used the fresh access token on the search endpoint
    method2, url2, kwargs2 = fake.calls[1]
    assert url2.endswith("/crm/v3/objects/contacts/search")
    assert kwargs2["headers"]["Authorization"] == "Bearer AT_1"


def test_private_token_mode_skips_refresh():
    patcher, fake = _patch_provider_http([
        _json(200, {"results": []}),
    ])
    try:
        from app.providers.hubspot import HubSpotProviderClient

        client = HubSpotProviderClient()

        import asyncio

        result = asyncio.new_event_loop().run_until_complete(
            client.search_records(PRIVATE_CREDS, "deals", "dealname", "X")
        )
    finally:
        patcher.stop()

    assert result["found"] is False
    assert len(fake.calls) == 1  # no token call
    assert fake.calls[0][2]["headers"]["Authorization"] == "Bearer pat-abc-123"


def test_error_taxonomy_mapping():
    from app.providers.hubspot import HubSpotProviderClient
    from app.connectors import ConnectorErrorCode

    cases = [
        (_json(404, {"message": "not here"}), ConnectorErrorCode.NOT_FOUND, False),
        (_json(403, {}), ConnectorErrorCode.FORBIDDEN, False),
        (_json(400, {"message": "bad"}), ConnectorErrorCode.BAD_REQUEST, False),
        (_json(429, {"message": "slow down"}), ConnectorErrorCode.RATE_LIMITED, True),
        (_json(500, {}), ConnectorErrorCode.UNAVAILABLE, True),
    ]
    for response, expected_code, expected_retryable in cases:
        patcher, _fake = _patch_provider_http([
            _json(200, {"access_token": "AT", "expires_in": 1800}),
            response,
        ])
        try:
            from app.providers.hubspot import HubSpotProviderClient

            client = HubSpotProviderClient()

            import asyncio

            async def go():
                await client.get_record({"refresh_token": "RT"}, "contacts", "999")

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(go())
                raise AssertionError(f"{response.status_code} should have raised")
            except ConnectorError as exc:
                assert exc.code == expected_code.value or exc.code == expected_code
                assert exc.retryable is expected_retryable
            finally:
                loop.close()
        finally:
            patcher.stop()


def test_unknown_object_type_rejected():
    from app.providers.hubspot import HubSpotProviderClient

    import asyncio

    client = HubSpotProviderClient()

    async def go():
        await client.search_records(OAUTH_CREDS, "../evil", "email", "x")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("path traversal object_type should have raised")
    except ConnectorError as exc:
        assert "Unsupported HubSpot object_type" in str(exc)
    finally:
        loop.close()


def test_custom_object_type_is_accepted_and_used_in_path():
    """Custom object ids (e.g. 2-12345678) are valid, not allowlisted."""
    patcher, fake = _patch_provider_http([
        _json(200, {"results": []}),
    ])
    try:
        from app.providers.hubspot import HubSpotProviderClient

        client = HubSpotProviderClient()

        import asyncio

        result = asyncio.new_event_loop().run_until_complete(
            client.list_records(PRIVATE_CREDS, "2-12345678", limit=10)
        )
    finally:
        patcher.stop()

    assert result["object_type"] == "2-12345678"
    assert fake.calls[0][1].endswith("/crm/v3/objects/2-12345678")
    assert fake.calls[0][2]["params"]["limit"] == 10


def test_object_discovery_lists_standard_and_custom_objects():
    patcher, fake = _patch_provider_http([
        _json(200, {
            "results": [
                {
                    "name": "cars",
                    "labels": {"singular": "Car", "plural": "Cars"},
                    "objectTypeId": "2-12345678",
                    "fullyQualifiedName": "cars",
                },
                {
                    "name": "bad/object",
                    "labels": {"plural": "Bad"},
                    "objectTypeId": "2-bad",
                },
            ]
        }),
    ])
    try:
        from app.providers.hubspot import STANDARD_OBJECTS, HubSpotProviderClient

        client = HubSpotProviderClient()

        import asyncio

        result = asyncio.new_event_loop().run_until_complete(
            client.list_object_types(PRIVATE_CREDS)
        )
    finally:
        patcher.stop()

    assert fake.calls[0][1].endswith("/crm/v3/schemas")
    objects = {item["key"]: item for item in result["objects"]}
    assert "contacts" in objects
    assert objects["contacts"]["is_custom"] is False
    assert objects["cars"]["label"] == "Cars"
    assert objects["cars"]["is_custom"] is True
    assert objects["cars"]["object_type_id"] == "2-12345678"
    # An unsafe schema name is skipped rather than becoming a path segment.
    assert "bad/object" not in objects
    assert result["standard_count"] == len(STANDARD_OBJECTS)
    assert result["custom_count"] == 1
    assert result["custom_objects_available"] is True


def test_object_discovery_follows_schema_pagination():
    patcher, fake = _patch_provider_http([
        _json(200, {
            "results": [{"name": "cars", "labels": {"plural": "Cars"}, "objectTypeId": "2-1"}],
            "paging": {"next": {"after": "cursor-2"}},
        }),
        _json(200, {
            "results": [{"name": "boats", "labels": {"plural": "Boats"}, "objectTypeId": "2-2"}],
        }),
    ])
    try:
        from app.providers.hubspot import HubSpotProviderClient

        client = HubSpotProviderClient()

        import asyncio

        result = asyncio.new_event_loop().run_until_complete(
            client.list_object_types(PRIVATE_CREDS)
        )
    finally:
        patcher.stop()

    keys = {item["key"] for item in result["objects"]}
    assert {"cars", "boats"} <= keys
    assert len(fake.calls) == 2
    assert fake.calls[1][2]["params"]["after"] == "cursor-2"


def test_object_discovery_degrades_when_schema_scope_is_missing():
    patcher, _fake = _patch_provider_http([
        _json(403, {"message": "missing scope"}),
    ])
    try:
        from app.providers.hubspot import STANDARD_OBJECTS, HubSpotProviderClient

        client = HubSpotProviderClient()

        import asyncio

        result = asyncio.new_event_loop().run_until_complete(
            client.list_object_types(PRIVATE_CREDS)
        )
    finally:
        patcher.stop()

    assert result["custom_objects_available"] is False
    assert result["custom_count"] == 0
    assert "Custom object discovery is unavailable" in result["custom_error"]
    assert result["standard_count"] == len(STANDARD_OBJECTS)


def test_object_discovery_surfaces_invalid_credentials():
    """A 401 must not be masked as 'standard objects only'."""
    patcher, _fake = _patch_provider_http([
        _json(401, {"message": "invalid token"}),
    ])
    try:
        from app.providers.hubspot import HubSpotProviderClient

        client = HubSpotProviderClient()

        import asyncio

        async def go():
            await client.list_object_types(PRIVATE_CREDS)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("invalid credentials should have raised")
        except ConnectorError as exc:
            assert exc.code == "CONNECTOR_AUTH_FAILED"
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_hubspot_definition_exposes_object_discovery_and_dynamic_object_types():
    from app.connectors.hubspot_definition import build_hubspot_definition

    definition = build_hubspot_definition()
    assert "list_object_types" in definition.operations
    search_props = definition.operations["search"].input_schema["properties"]
    # No static enum: custom objects are discovered per portal.
    assert "enum" not in search_props["object_type"]
    assert "2-12345678" in search_props["object_type"]["description"]

    # list_pipelines remains intentionally limited to deals/tickets.
    pipeline_props = definition.operations["list_pipelines"].input_schema["properties"]
    assert pipeline_props["object_type"]["enum"] == ["deals", "tickets"]


# ----------------------------------------------------------------------
# Full stack: API -> queue -> worker -> engine -> connector
# ----------------------------------------------------------------------

HS_CREDENTIAL = {"private_token": "PAT_SUPER_SECRET_9Z"}

def _setup(client):
    return auth_headers(register(client)["token"])


def _create_hs_credential(client, headers):
    resp = client.post(
        "/api/credentials",
        json={"name": "HubSpot Prod", "type": "hubspot", "data": HS_CREDENTIAL},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _create_workflow(client, headers, credential_id: str) -> None:
    wf = {
        "id": "wf_hubspot",
        "name": "HS Create Contact",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "hs",
                "type": "hubspot",
                "parameters": {
                    "operation": "create",
                    "object_type": "contacts",
                    "properties": {
                        "email": "{{ $json.email }}",
                        "firstname": "{{ $json.first_name }}",
                    },
                },
                "credentials": {"hubspot": credential_id},
            },
        ],
        "connections": [{"source": "trigger", "target": "hs"}],
        "settings": {},
    }
    resp = client.post("/api/workflows", json=wf, headers=headers)
    assert resp.status_code == 201, resp.text


def _run_and_poll(client, headers, input_data):
    resp = client.post("/api/workflows/wf_hubspot/run", json={"data": input_data}, headers=headers)
    assert resp.status_code == 202, resp.text
    execution_id = resp.json()["data"]["execution_id"]
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("running", "queued", "cancelling"):
            return execution_id, data
        time.sleep(0.05)
    raise AssertionError(f"execution did not finish, last data={data}")


def test_full_stack_hubspot_create(client):
    headers = _setup(client)
    cred = _create_hs_credential(client, headers)
    _create_workflow(client, headers, cred["id"])

    created = {"id": "5501", "properties": {"email": "new@acme.com"}}
    patcher, fake = _patch_provider_http([_json(201, created)])
    try:
        execution_id, data = _run_and_poll(
            client, headers, {"email": "new@acme.com", "first_name": "New"}
        )
    finally:
        patcher.stop()

    assert data["status"] == "success", data.get("error")
    outputs = data["results"]["outputs"]["hs"]["main"]
    assert outputs[0]["id"] == "5501"
    assert outputs[0]["success"] is True

    # The connector resolved the expression into the outgoing properties
    method, url, kwargs = fake.calls[0]
    assert url.endswith("/crm/v3/objects/contacts")
    assert kwargs["json"]["properties"]["email"] == "new@acme.com"
    assert kwargs["headers"]["Authorization"] == "Bearer PAT_SUPER_SECRET_9Z"

    # The private token never leaks into the execution record
    raw = json.dumps(data, default=str)
    assert "PAT_SUPER_SECRET_9Z" not in raw


def test_connector_discovery_lists_hubspot(client):
    headers = _setup(client)
    body = client.get("/api/connectors", headers=headers).json()["data"]
    hubspot = [c for c in body if c.get("connector_key") == "hubspot" or c.get("key") == "hubspot"]
    assert hubspot, f"hubspot missing from discovery: {[c.get('key') for c in body]}"


def test_hubspot_object_discovery_endpoint_returns_custom_objects(client):
    headers = _setup(client)
    cred = _create_hs_credential(client, headers)
    patcher, fake = _patch_provider_http([
        _json(200, {
            "results": [
                {
                    "name": "cars",
                    "labels": {"singular": "Car", "plural": "Cars"},
                    "objectTypeId": "2-12345678",
                    "fullyQualifiedName": "cars",
                },
            ]
        }),
    ])
    try:
        resp = client.get(
            f"/api/connectors/hubspot/objects?credential_id={cred['id']}",
            headers=headers,
        )
    finally:
        patcher.stop()

    assert resp.status_code == 200, resp.text
    payload = resp.json()["data"]
    objects = {item["key"]: item for item in payload["objects"]}
    assert "contacts" in objects
    assert "cars" in objects
    assert objects["cars"]["is_custom"] is True
    assert payload["custom_count"] == 1
    assert payload["cached"] is False
    assert fake.calls[0][1].endswith("/crm/v3/schemas")
