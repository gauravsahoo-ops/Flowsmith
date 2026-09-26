"""Microsoft Dynamics 365 / Dataverse connector unit & integration tests.

Tests:
- Connector discovery and registration.
- Provider client operations: query (OData & FetchXML), get, create, update, delete, WhoAmI.
- Authentication modes: OAuth token refresh and Client Credentials (S2S).
- ConnectorSDK op_execute dispatch.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.connectors import get_registry, register_builtin_connectors
from app.connectors.dynamics_crm_connector import DynamicsCrmConnector
from app.providers.dynamics_crm import DynamicsCrmProviderClient


def _settings(**overrides) -> Settings:
    defaults = {
        "dynamics_crm_client_id": "DYN_CID",
        "dynamics_crm_client_secret": "DYN_SECRET",
        "dynamics_crm_instance_url": "https://testorg.crm.dynamics.com",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class FakeHTTPClient:
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
            raise AssertionError(f"Unexpected extra call: {method} {url}")
        return self.responses.pop(0)


def _json(status: int, payload: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        headers=headers or {},
        request=httpx.Request("GET", "https://fake.crm.dynamics.com"),
    )


def _patch_provider_http(responses: list[httpx.Response]):
    fake = FakeHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.dynamics_crm.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


OAUTH_CREDS = {
    "instance_url": "https://testorg.crm.dynamics.com",
    "auth_type": "oauth2",
    "refresh_token": "RT_TEST_123",
    "oauth": True,
}

S2S_CREDS = {
    "instance_url": "https://testorg.crm.dynamics.com",
    "auth_type": "client_credentials",
    "client_id": "CLIENT_1",
    "client_secret": "SECRET_1",
    "tenant_id": "tenant-123",
}


@pytest.fixture(autouse=True)
def _connectors_and_settings(monkeypatch):
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    monkeypatch.setattr("app.providers.dynamics_crm.get_settings", lambda: _settings())
    yield


def test_connector_discovery_lists_dynamics():
    registry = get_registry()
    connector = registry.get("dynamics_crm")
    assert connector is not None
    assert connector.connector_id == "dynamics_crm"
    assert "dynamics_crm" in connector.node_types

    definition = registry.get_definition("dynamics_crm")
    assert definition is not None
    assert "query" in definition.operations
    assert "create" in definition.operations
    assert "update" in definition.operations
    assert "delete" in definition.operations
    assert "dynamics_crm" in definition.credential_types


def test_dynamics_provider_query_odata():
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_1", "expires_in": 3600}),  # token refresh
        _json(200, {"value": [{"contactid": "guid-1", "fullname": "Jane Doe"}]}),  # query
    ])
    try:
        client = DynamicsCrmProviderClient()
        records = asyncio.run(
            client.query(
                OAUTH_CREDS,
                "contacts",
                filter_expr="statecode eq 0",
                select=["fullname", "emailaddress1"],
                top=10,
            )
        )
    finally:
        patcher.stop()

    assert len(records) == 1
    assert records[0]["fullname"] == "Jane Doe"

    # Verify query URL
    method, url, kwargs = fake.calls[1]
    assert method == "GET"
    assert "https://testorg.crm.dynamics.com/api/data/v9.2/contacts?" in url
    assert "%24filter=statecode+eq+0" in url or "$filter=statecode+eq+0" in url
    assert "%24top=10" in url or "$top=10" in url
    assert kwargs["headers"]["Authorization"] == "Bearer AT_1"


def test_dynamics_provider_query_fetchxml():
    fetch_xml = "<fetch><entity name='contact'><attribute name='fullname'/></entity></fetch>"
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_1", "expires_in": 3600}),
        _json(200, {"value": [{"fullname": "John Smith"}]}),
    ])
    try:
        client = DynamicsCrmProviderClient()
        records = asyncio.run(
            client.query(OAUTH_CREDS, "contacts", fetch_xml=fetch_xml)
        )
    finally:
        patcher.stop()

    assert len(records) == 1
    assert records[0]["fullname"] == "John Smith"
    method, url, kwargs = fake.calls[1]
    assert "fetchXml=" in url


def test_dynamics_provider_crud_operations():
    record_guid = "00000000-0000-0000-0000-000000000002"
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_1", "expires_in": 3600}),
        _json(201, {"id": record_guid, "fullname": "Alice"}, {"OData-EntityId": f"https://testorg.crm.dynamics.com/api/data/v9.2/contacts({record_guid})"}),
        _json(200, {"contactid": record_guid, "fullname": "Alice"}),
        _json(200, {"contactid": record_guid, "updated": True}),
        _json(204, {}),
    ])
    try:
        client = DynamicsCrmProviderClient()
        # Create
        created = asyncio.run(client.create_record(OAUTH_CREDS, "contacts", {"firstname": "Alice"}))
        assert created.get("id") == record_guid or created.get("fullname") == "Alice"

        # Get
        retrieved = asyncio.run(client.get_record(OAUTH_CREDS, "contacts", record_guid))
        assert retrieved["fullname"] == "Alice"

        # Update
        updated = asyncio.run(client.update_record(OAUTH_CREDS, "contacts", record_guid, {"lastname": "Wonderland"}))
        assert updated.get("updated") is True or updated.get("contactid") == record_guid

        # Delete
        deleted = asyncio.run(client.delete_record(OAUTH_CREDS, "contacts", record_guid))
        assert deleted["deleted"] is True
    finally:
        patcher.stop()


def test_dynamics_provider_client_credentials():
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "S2S_TOKEN_999", "expires_in": 3600}),
        _json(200, {"UserId": "usr-1", "OrganizationId": "org-1"}),
    ])
    try:
        client = DynamicsCrmProviderClient()
        res = asyncio.run(client.who_am_i(S2S_CREDS))
        assert res["UserId"] == "usr-1"
        assert res["OrganizationId"] == "org-1"
    finally:
        patcher.stop()

    # Verify S2S grant
    method, url, kwargs = fake.calls[0]
    assert url == "https://login.microsoftonline.com/tenant-123/oauth2/v2.0/token"
    assert kwargs["data"]["grant_type"] == "client_credentials"
    assert kwargs["data"]["client_id"] == "CLIENT_1"
    assert kwargs["data"]["scope"] == "https://testorg.crm.dynamics.com/.default"


def test_dynamics_connector_op_execute_dispatch():
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_1", "expires_in": 3600}),
        _json(200, {"value": [{"accountid": "acc-1", "name": "Contoso"}]}),
    ])
    try:
        connector = DynamicsCrmConnector()
        res = asyncio.run(
            connector.op_execute(
                "query",
                {"entity": "accounts", "filter": "name eq 'Contoso'"},
                {"credentials": {"dynamics_crm": OAUTH_CREDS}},
            )
        )
        assert res["count"] == 1
        assert res["records"][0]["name"] == "Contoso"
    finally:
        patcher.stop()


def test_dynamics_connector_engine_generic_execute_dispatch():
    """Verify Flowsmith engine convention op_execute('execute', payload, context) routes correctly."""
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_1", "expires_in": 3600}),
        _json(200, {"contactid": "guid-99", "fullname": "Jane Doe"}),
    ])
    try:
        connector = DynamicsCrmConnector()
        # Engine calls op_execute("execute", payload)
        res = asyncio.run(
            connector.op_execute(
                "execute",
                {"operation": "get", "entity": "contacts", "record_id": "guid-99"},
                {"credentials": {"dynamics_crm": OAUTH_CREDS}},
            )
        )
        assert res["contactid"] == "guid-99"
        assert res["fullname"] == "Jane Doe"
    finally:
        patcher.stop()


def test_dynamics_connector_smart_search_and_data_extraction():
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_1", "expires_in": 3600}),
        _json(200, {"value": [{"contactid": "c-1", "fullname": "Sarah Connor"}]}),
    ])
    try:
        connector = DynamicsCrmConnector()
        res = asyncio.run(
            connector.op_execute(
                "search",
                {"entity": "contacts", "query": "Sarah"},
                {"credentials": {"dynamics_crm": OAUTH_CREDS}},
            )
        )
        assert res["count"] == 1
        # Check that contains(fullname, 'Sarah') filter was constructed
        method, url, _ = fake.calls[1]
        assert "contains(fullname" in url or "Sarah" in url
    finally:
        patcher.stop()


def test_dynamics_provider_query_auto_pagination():
    patcher, fake = _patch_provider_http([
        _json(200, {"access_token": "AT_PAGE", "expires_in": 3600}),
        _json(200, {
            "value": [{"accountid": "1", "name": "Page 1"}],
            "@odata.nextLink": "https://testorg.crm.dynamics.com/api/data/v9.2/accounts?$skiptoken=skip1",
        }),
        _json(200, {
            "value": [{"accountid": "2", "name": "Page 2"}],
        }),
    ])
    try:
        client = DynamicsCrmProviderClient()
        records = asyncio.run(client.query(OAUTH_CREDS, "accounts"))
        assert len(records) == 2
        assert records[0]["name"] == "Page 1"
        assert records[1]["name"] == "Page 2"
    finally:
        patcher.stop()

