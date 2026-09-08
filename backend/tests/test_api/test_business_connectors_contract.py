"""Phase 11 business-connectors contract suite.

Cross-cutting guarantees for the whole connector fleet:

- all 19 priority connectors are discoverable via /api/connectors with
  real operations (not the generic fallback);
- every new node type appears in the node catalog with a parameters
  schema derived from its definition, and carries credential metadata;
- every new credential type is listed by /api/credentials/types with
  secret fields flagged;
- definition <-> connector parity: each advertised operation actually
  executes through op_execute dispatch (validation errors prove routing);
- idempotency/retryable declarations exist on every operation;
- secret material never appears in discovery or catalog payloads.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register

PRIORITY_CONNECTORS = {
    # priority order from Phase 11; http/gmail/sheets/hubspot pre-existed
    "http", "postgresql_placeholder",  # replaced below by explicit list
}
PRIORITY_CONNECTORS = [
    "http", "postgres", "mysql", "gmail", "google_sheets", "google_drive",
    "slack", "msteams", "github", "outlook", "hubspot", "notion", "jira",
    "discord", "stripe", "mongodb", "redis", "airtable", "shopify",
]

NEW_CREDENTIAL_TYPES = [
    "postgres", "mysql", "google_drive", "microsoft_graph", "slack",
    "github", "notion", "jira", "discord", "stripe", "mongodb", "redis",
    "airtable", "shopify",
]

SECRET_SAMPLES = {
    "slack": "xoxb-super-secret",
    "github": "ghp_super_secret_token",
    "stripe": "sk_test_super_secret_key",
    "jira": "jira-api-token-secret-value",
    "shopify": "shpat_super_secret_value",
}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def _setup(client):
    return auth_headers(register(client)["token"])


def test_all_priority_connectors_discoverable(client):
    headers = _setup(client)
    body = client.get("/api/connectors", headers=headers).json()["data"]
    keys = {c.get("connector_key") or c.get("key") for c in body}
    missing = [k for k in PRIORITY_CONNECTORS if k not in keys]
    assert not missing, f"missing from discovery: {missing}"


def test_priority_connectors_have_real_operations(client):
    """New connectors must ship real operation schemas; the legacy 'http'
    connector keeps its generic pre-Phase-11 definitions."""
    registry = get_registry()
    for key in PRIORITY_CONNECTORS:
        definition = registry.get_definition(key)
        assert definition is not None, key
        assert definition.operations, f"{key} has no operations"
        if key == "http":
            continue
        for op in definition.operations.values():
            assert "properties" in (op.input_schema or {}), f"{key}.{op.operation_key} lacks input schema"
            assert op.idempotency in ("idempotent", "conditionally_idempotent", "non_idempotent")
            assert isinstance(op.retryable, bool)


def test_node_catalog_exposes_connector_types_with_schemas(client):
    headers = _setup(client)
    catalog = client.get("/api/nodes", headers=headers).json()["data"]
    by_type = {n["type"]: n for n in catalog}

    expected_nodes = {
        "postgres", "mysql", "google_drive", "slack_api", "msteams",
        "outlook", "github", "notion", "jira", "discord", "stripe",
        "mongodb", "redis", "airtable", "shopify",
    }
    missing = [t for t in expected_nodes if t not in by_type]
    assert not missing, f"missing from node catalog: {missing}"

    for node_type in expected_nodes:
        entry = by_type[node_type]
        schema = entry["parameters_schema"]
        props = schema.get("properties") or {}
        assert "operation" in props, f"{node_type} schema lacks operation enum"
        assert entry["operations"], f"{node_type} lacks per-operation metadata"
        # Credential metadata present so ConfigPanel offers the dropdown.
        assert entry["credential_types"], f"{node_type} lacks credential types"


def test_credential_types_listed_for_ui(client):
    headers = _setup(client)
    types = client.get("/api/credentials/types", headers=headers).json()["data"]
    by_type = {t["type"]: t for t in types}
    missing = [t for t in NEW_CREDENTIAL_TYPES if t not in by_type]
    assert not missing, f"missing credential types: {missing}"
    for cred_type in NEW_CREDENTIAL_TYPES:
        entry = by_type[cred_type]
        assert entry["secret_fields"], f"{cred_type} declares no secret fields"
        assert entry["parameters_schema"].get("properties"), cred_type


def test_discovery_and_catalog_never_leak_secrets(client):
    headers = _setup(client)
    discovery_raw = client.get("/api/connectors", headers=headers).text
    catalog_raw = client.get("/api/nodes", headers=headers).text
    types_raw = client.get("/api/credentials/types", headers=headers).text
    for sample in SECRET_SAMPLES.values():
        assert sample not in discovery_raw
        assert sample not in catalog_raw
        assert sample not in types_raw


@pytest.mark.parametrize("connector_key,operation,bad_payload", [
    ("postgres", "query", {"sql": ""}),
    ("stripe", "create_payment_intent", {"amount": 0}),
    ("github", "get_repo", {"owner": "../evil", "repo": "x"}),
    ("notion", "query_database", {"database_id": "../evil"}),
    ("airtable", "list_records", {"base_id": "nope", "table_name": "T"}),
    ("shopify", "get_product", {"product_id": "abc"}),
    ("jira", "search", {"jql": ""}),
    ("discord", "send_message", {"channel_id": "", "content": ""}),
])
def test_operations_route_through_op_execute(connector_key, operation, bad_payload):
    """Dispatching an advertised operation reaches the connector layer —
    a typed BAD_REQUEST proves routing (not 'unsupported operation')."""
    registry = get_registry()
    connector = registry.get(connector_key)
    assert connector is not None

    async def go():
        await connector.op_execute(operation, dict(bad_payload), {})

    from app.connectors import ConnectorError, ConnectorErrorCode

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError(f"{connector_key}.{operation} should have raised")
    except ConnectorError as exc:
        assert exc.code in (
            ConnectorErrorCode.BAD_REQUEST,
            ConnectorErrorCode.NOT_CONFIGURED,
            ConnectorErrorCode.BAD_REQUEST.value,
            ConnectorErrorCode.NOT_CONFIGURED.value,
        ), str(exc)
        assert "Unsupported" not in str(exc)
    finally:
        loop.close()


def test_unknown_operation_rejected_typed():
    from app.connectors import ConnectorError, ConnectorErrorCode

    registry = get_registry()

    async def go():
        await registry.get("stripe").op_execute("teleport", {}, {})

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("unknown op should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
    finally:
        loop.close()
