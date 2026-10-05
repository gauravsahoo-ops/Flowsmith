"""Salesforce connector definition tests (Phase 6).

Verifies that Salesforce is registered through the ConnectorRegistry
with an explicit, validated ConnectorDefinitionV1: discoverable, with
the initial operation set, credential requirements, and schemas that
match what the connector actually consumes.
"""

from __future__ import annotations

import pytest

from app.api.nodes import _connector_catalog_entries, _connector_operation_enum
from app.connectors import (
    ConnectorError,
    ConnectorErrorCode,
    ConnectorLifecycle,
    get_registry,
    register_builtin_connectors,
)
from app.connectors.registry import validate_definition
from app.connectors.salesforce_definition import build_salesforce_definition


@pytest.fixture(autouse=True)
def _clean_registry():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    yield
    registry.initialize()
    register_builtin_connectors()


def test_built_definition_is_valid():
    """The definition itself passes registry validation."""
    validate_definition(build_salesforce_definition())


def test_salesforce_registered_through_framework():
    registry = get_registry()
    assert registry.get("salesforce") is not None
    definition = registry.get_definition("salesforce")
    assert definition is not None
    assert definition.connector_key == "salesforce"
    assert definition.connector_version == "1.2.0"
    assert definition.lifecycle_status == ConnectorLifecycle.STABLE.value


def test_salesforce_discoverable_in_registry_list():
    registry = get_registry()
    keys = {c.connector_id for c in registry.list_all()}
    assert "salesforce" in keys
    assert registry.get_definition("salesforce").operations


def test_full_operations_discoverable():
    """Phase 9: full operation surface — CRUD + upsert + SOQL +
    discovery (describe/list) + Bulk API 2.0."""
    definition = get_registry().get_definition("salesforce")
    ops = definition.operations
    # Core CRUD + search (Phase 8 set)
    for key in ("search", "get", "create", "update", "delete", "query"):
        assert key in ops
    # Phase 9 additions: idempotent write, discovery, bulk
    for key in ("upsert", "describe", "list", "bulk"):
        assert key in ops
    assert ops["search"].display_name == "Search/Get Record"


def test_operations_are_consistent_with_definition():
    definition = get_registry().get_definition("salesforce")
    for key, op in definition.operations.items():
        assert op.operation_key == key
        assert op.connector_key == "salesforce"
        assert op.connector_version == "1.2.0"
        assert op.operation_version == "1.1.0"
        assert op.credential_require == "salesforce"
        assert op.input_schema["type"] == "object"


def test_phase9_operation_schemas_match_connector_parameters():
    """Required inputs mirror what the connector validates server-side."""
    ops = get_registry().get_definition("salesforce").operations
    assert ops["get"].input_schema["required"] == ["object_name", "record_id"]
    assert ops["create"].input_schema["required"] == ["object_name", "record"]
    assert ops["update"].input_schema["required"] == ["object_name", "record_id", "record"]
    assert ops["delete"].input_schema["required"] == ["object_name", "record_id"]
    assert ops["query"].input_schema["required"] == ["soql"]
    assert ops["search"].input_schema["required"] == ["object_name", "search_field", "search_value"]
    # Phase 9 operations
    assert ops["upsert"].input_schema["required"] == [
        "object_name", "external_id_field", "external_id", "record",
    ]
    assert ops["describe"].input_schema["required"] == ["object_name"]
    assert ops["list"].input_schema["required"] == []
    assert ops["bulk"].input_schema["required"] == ["object_name", "bulk_operation", "records"]
    bulk_props = ops["bulk"].input_schema["properties"]
    assert bulk_props["bulk_operation"]["enum"] == ["insert", "update", "upsert", "delete"]


def test_operation_schemas_match_connector_parameters():
    """Required inputs mirror what the connector validates server-side."""
    ops = get_registry().get_definition("salesforce").operations
    assert ops["get"].input_schema["required"] == ["object_name", "record_id"]
    assert ops["create"].input_schema["required"] == ["object_name", "record"]
    assert ops["update"].input_schema["required"] == ["object_name", "record_id", "record"]
    assert ops["delete"].input_schema["required"] == ["object_name", "record_id"]
    assert ops["query"].input_schema["required"] == ["soql"]
    assert ops["search"].input_schema["required"] == ["object_name", "search_field", "search_value"]


def test_retryable_advertised_matches_runtime_semantics():
    """Definition metadata (Phase 16/9): every operation the engine safely
    retries on transient provider errors advertises retryable=True;
    create and bulk-insert (non-idempotent) stay False and are never
    auto-retried; bulk as a whole advertises conservatively."""
    ops = get_registry().get_definition("salesforce").operations
    for key in ("search", "get", "update", "upsert", "delete", "query",
                "describe", "list"):
        assert ops[key].retryable is True, key
    assert ops["create"].retryable is False
    assert ops["bulk"].retryable is False


def test_credential_requirements_discoverable():
    definition = get_registry().get_definition("salesforce")
    credential_types = definition.credential_types
    assert "salesforce" in credential_types
    cred = credential_types["salesforce"]
    assert cred.type_key == "salesforce"
    assert cred.secret_fields == ["client_secret", "password", "refresh_token"]
    assert cred.encryption_required is True
    props = cred.validation_schema["properties"]
    for field in ("instance_url", "client_id", "client_secret", "username", "password", "refresh_token"):
        assert field in props


def test_catalog_enum_derives_from_definition():
    definition = get_registry().get_definition("salesforce")
    assert _connector_operation_enum("salesforce") == list(definition.operations.keys())
    entries = {e["type"]: e for e in _connector_catalog_entries()}
    enum = entries["salesforce"]["parameters_schema"]["properties"]["operation"]["enum"]
    assert enum == ["search", "get", "create", "update", "upsert", "delete",
                    "query", "describe", "list", "bulk", "custom_api_call", "flow_invoke"]


def test_catalog_exposes_per_operation_metadata():
    """Phase 9: the catalog entry carries per-operation idempotency and
    retryable flags so the UI can show accurate badges."""
    entries = {e["type"]: e for e in _connector_catalog_entries()}
    ops_meta = entries["salesforce"]["operations"]
    assert ops_meta["create"]["idempotency"] == "non_idempotent"
    assert ops_meta["create"]["retryable"] is False
    assert ops_meta["get"]["retryable"] is True
    assert ops_meta["upsert"]["idempotency"] == "idempotent"
    # Node-level badge stays honest: mixed safety => conditionally.
    assert entries["salesforce"]["idempotency"] == "conditionally_idempotent"


def test_idempotency_classification():
    """Create is non-idempotent and never retryable (Phase 9/16); bulk
    spans insert (unsafe) so it is conditional; upsert is a safe retry;
    discovery and reads are idempotent."""
    ops = get_registry().get_definition("salesforce").operations
    assert ops["create"].idempotency == "non_idempotent"
    assert ops["create"].retryable is False
    assert ops["bulk"].idempotency == "conditionally_idempotent"
    for key in ("search", "get", "update", "upsert", "delete", "query",
                "describe", "list"):
        assert ops[key].idempotency == "idempotent"


def test_validation_guards_broken_definitions():
    """The real definition passes; tampered ones are still rejected."""
    definition = build_salesforce_definition()
    definition.operations["get"].credential_require = "does_not_exist"
    with pytest.raises(ConnectorError) as excinfo:
        validate_definition(definition)
    assert excinfo.value.code == ConnectorErrorCode.VALIDATION_FAILED.value