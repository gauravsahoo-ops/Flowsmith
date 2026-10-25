"""Unit and integration tests for Flowsmith catalog-only connectors.

Catalog-only connectors are generic HTTP adapters, not native vendor
implementations. These tests pin the truthful behavior: a real endpoint is
required, and no synthetic success is allowed.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors import (
    ConnectorError,
    ConnectorErrorCode,
    get_registry,
    register_builtin_connectors,
)


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


def test_parity_connectors_registered_count():
    """Verify that all parity connectors are registered and definitions are valid."""
    reg = get_registry()
    definitions = reg.list_definitions()
    all_connectors = reg.list_all()

    # The registry exposes 500+ names, but only a subset are native integrations.
    # See docs/CONNECTOR_STATUS.md for the truthful split.
    assert len(definitions) >= 500
    assert len(all_connectors) >= 500

    # Check key enterprise connectors are in the registry
    expected_sample = [
        "salesforce", "hubspot", "dynamics_crm", "postgres", "mysql",
        "mssql", "sqlite", "rabbitmq", "action_network", "adalo",
        "bamboo_hr", "chargebee", "circle_ci", "confluence", "contentful"
    ]
    def_keys = {d.connector_key for d in definitions}
    for key in expected_sample:
        assert key in def_keys, f"Expected {key} to be registered in definitions"


@pytest.mark.asyncio
async def test_catalog_only_connector_requires_endpoint():
    """A catalog-only connector must fail loudly, never fabricate success."""
    reg = get_registry()
    conn = reg.get("adalo")
    assert conn is not None

    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute(
            operation="get",
            payload={"parameters": {"employee_id": "EMP-100"}},
        )

    assert exc_info.value.code == ConnectorErrorCode.NOT_CONFIGURED.value
    assert "catalog-only" in str(exc_info.value).lower()
    assert "endpoint_url" in str(exc_info.value)


@pytest.mark.asyncio
async def test_catalog_only_connector_executes_with_explicit_endpoint():
    """With an explicit endpoint, the generic HTTP adapter performs real I/O."""
    reg = get_registry()
    conn = reg.get("adalo")
    assert conn is not None

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"employees": [{"id": "EMP-100"}]}
    response.text = '{"employees": [{"id": "EMP-100"}]}'

    with patch("app.security.safe_http_client.get_safe_http_client") as client_factory:
        client = AsyncMock()
        client.request.return_value = response
        client_factory.return_value = client

        result = await conn.op_execute(
            operation="get",
            payload={
                "endpoint_url": "https://api.example.com/employees",
                "parameters": {"employee_id": "EMP-100"},
            },
        )

    assert result["status"] == "success"
    assert result["connector_id"] == "adalo"
    assert result["operation"] == "get"
    assert result["data"] == {"employees": [{"id": "EMP-100"}]}
    client.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_parity_connector_disconnect_and_reconnect():
    """Verify lifecycle of parity connector."""
    reg = get_registry()
    conn = reg.get("chargebee")
    assert conn is not None

    connected = await conn.connect({"api_key": "test_key"})
    assert connected is True
    assert conn.status == "connected"

    await conn.disconnect()
    assert conn.status == "disconnected"


def test_catalog_only_scope_breakdown():
    """Native conversion targets must exclude node shadows and trigger aliases."""
    from collections import Counter

    from app.connectors.parity_connectors import ParityConnector
    from app.nodes.registry import NODE_REGISTRY

    registry = get_registry()
    scopes = Counter()
    for definition in registry.list_definitions():
        if not isinstance(registry.get(definition.connector_key), ParityConnector):
            continue
        if definition.connector_key in NODE_REGISTRY:
            scopes["node_shadow"] += 1
        elif definition.triggers or definition.connector_key.endswith("_trigger"):
            scopes["trigger_alias"] += 1
        else:
            scopes["vendor"] += 1
    assert scopes == {"vendor": 257, "trigger_alias": 95, "node_shadow": 73}


def test_catalog_only_definitions_are_labelled():
    """UI and docs must be able to distinguish catalog-only from native."""
    from app.connectors.parity_connectors import ParityConnector

    registry = get_registry()
    catalog_count = 0
    for definition in registry.list_definitions():
        connector = registry.get(definition.connector_key)
        if not isinstance(connector, ParityConnector):
            continue
        catalog_count += 1
        assert definition.metadata.get("implementation") == "catalog_only"
        assert definition.metadata.get("requires_endpoint") is True

    assert catalog_count >= 400


def test_parity_connector_definitions_schema_validity():
    """Verify every definition, not a sample, has a valid contract."""
    reg = get_registry()
    definitions = reg.list_definitions()
    assert len(definitions) >= 500
    for defn in definitions:
        assert defn.connector_key
        assert defn.display_name
        assert re.match(r"^\d+\.\d+\.\d+$", defn.connector_version)
        assert defn.lifecycle_status in ("stable", "beta", "internal", "draft")
        assert len(defn.operations) > 0 or len(defn.triggers) > 0


@pytest.mark.asyncio
async def test_every_catalog_only_connector_requires_endpoint():
    """Every catalog-only connector must fail loudly without endpoint_url."""
    from app.connectors.parity_connectors import ParityConnector

    reg = get_registry()
    checked = 0
    for definition in reg.list_definitions():
        connector = reg.get(definition.connector_key)
        if not isinstance(connector, ParityConnector):
            continue
        checked += 1
        operation = next(iter(definition.operations), "execute")
        with pytest.raises(ConnectorError) as exc_info:
            await connector.op_execute(operation, {})
        assert exc_info.value.code == ConnectorErrorCode.NOT_CONFIGURED.value
        assert "endpoint_url" in str(exc_info.value)
    assert checked >= 400


@pytest.mark.asyncio
async def test_every_catalog_only_connector_executes_with_endpoint():
    """Every catalog-only connector must make a real adapter request."""
    from app.connectors.parity_connectors import ParityConnector

    reg = get_registry()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"ok": True}
    response.text = '{"ok": true}'

    with patch("app.security.safe_http_client.get_safe_http_client") as client_factory:
        client = AsyncMock()
        client.request.return_value = response
        client_factory.return_value = client

        checked = 0
        for definition in reg.list_definitions():
            connector = reg.get(definition.connector_key)
            if not isinstance(connector, ParityConnector):
                continue
            checked += 1
            operation = next(iter(definition.operations), "execute")
            result = await connector.op_execute(
                operation,
                {"endpoint_url": "https://api.example.com/resource"},
            )
            assert result["status"] == "success"
            assert result["connector_id"] == definition.connector_key
        assert checked >= 400
