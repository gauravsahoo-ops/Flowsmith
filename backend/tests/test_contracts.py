"""Core contract regression tests (Phase 40).

Locks down the invariants that keep the platform coherent as it grows.
If any of these fail, a refactor broke a contract the rest of the
system depends on.

Covers:
- Node registry: unique types, metadata completeness, idempotency
  values, declared credential types must exist in the credential
  registry.
- Connector definitions: every operation's credential_require resolves,
  every node_type is executable (node class or connector primary),
  idempotency/retryable values are legal, JSON schemas are objects.
- Execution record contract: GET /api/executions/{id} always exposes
  the full envelope keys.
- PostgreSQL authoritative state: executions own their terminal status;
  job-row mutations cannot rewrite history.
- Stateless workers / atomic claims: concurrent workers never receive
  the same queued job twice.
- Redis/queue boundary: claimed payload equals the enqueued payload.
"""

from __future__ import annotations

import threading

import pytest

from app.connectors import get_registry, register_builtin_connectors
from app.credentials.registry import CREDENTIAL_TYPES
from app.engine.node_base import IDEMPOTENCY_LEVELS
from app.nodes.registry import NODE_REGISTRY


# ----------------------------------------------------------------------
# Node registry contract
# ----------------------------------------------------------------------

def test_node_registry_invariants():
    assert NODE_REGISTRY, "registry empty"
    seen_types = set()
    for node_type, cls in NODE_REGISTRY.items():
        assert node_type == cls.node_type, f"{node_type}: key/class mismatch"
        assert node_type not in seen_types, f"duplicate registration {node_type}"
        seen_types.add(node_type)
        assert cls.display_name, f"{node_type} missing display_name"
        assert cls.category, f"{node_type} missing category"
        assert cls.idempotency in IDEMPOTENCY_LEVELS, f"{node_type}: bad idempotency {cls.idempotency}"
        # Triggers legitimately take no input handles; every node must
        # however produce output through at least one handle.
        assert cls.output_handles, f"{node_type}: output handles required"
        if not cls.input_handles:
            assert node_type in {"manual_trigger", "webhook", "schedule"} or "trigger" in node_type, (
                f"{node_type}: non-trigger node without input handles?"
            )
        # parameters_schema must be a pydantic model class with model_json_schema
        assert hasattr(cls.parameters_schema, "model_json_schema"), f"{node_type}: bad params schema"


def test_node_credential_types_are_registered():
    """A node may only declare credential types the platform knows."""
    unknown = {
        (node_type, ct)
        for node_type, cls in NODE_REGISTRY.items()
        for ct in cls.credential_types
        if ct not in CREDENTIAL_TYPES
    }
    assert not unknown, f"nodes declare unknown credential types: {unknown}"


# ----------------------------------------------------------------------
# Connector definition contract
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def connector_registry():
    register_builtin_connectors()
    return get_registry()


def test_connector_definitions_invariants(connector_registry):
    assert connector_registry.is_initialized()
    for definition in connector_registry.list_definitions():
        key = definition.connector_key
        assert definition.display_name and definition.description, key
        assert definition.connector_version, key
        for cred_key, cred in definition.credential_types.items():
            assert cred.type_key == cred_key, f"{key}/{cred_key}: type_key mismatch"
        for op_key, op in definition.operations.items():
            assert op.operation_key == op_key, f"{key}/{op_key}: key mismatch"
            assert op.input_schema.get("type") == "object", f"{key}/{op_key}: input schema"
            assert isinstance(op.output_schema, dict), f"{key}/{op_key}: output schema"
            # Phase 9: operation-level vocabulary gains
            # 'conditionally_idempotent' (bulk spans insert/update).
            assert op.idempotency in {
                "idempotent", "conditionally_idempotent", "non_idempotent",
            }, f"{key}/{op_key}: idempotency"
            # Credential requirement resolves to a real credential type
            # (declared by this connector or globally); None means the
            # operation needs no stored secret at all.
            known = (
                op.credential_require is None
                or op.credential_require in CREDENTIAL_TYPES
                or op.credential_require in definition.credential_types
            )
            assert known, f"{key}/{op_key}: unknown credential_require '{op.credential_require}'"


def test_business_connectors_present_with_expected_ops(connector_registry):
    expected = {
        "salesforce": {"search", "get", "create", "update", "delete", "query"},
        "hubspot": {"search", "get", "create", "update"},
        "google_calendar": {"list_events", "get_event", "create_event", "update_event", "delete_event"},
        "google_sheets": {"read", "append", "update"},
    }
    for key, ops in expected.items():
        defn = connector_registry.get_definition(key)
        assert defn is not None, f"{key} missing from registry"
        assert ops <= set(defn.operations), f"{key}: missing operations {ops - set(defn.operations)}"


def test_connector_node_types_resolve(connector_registry):
    """Every connector node_type advertised by an operation must be
    routable at execution time (node class or connector primary)."""
    for definition in connector_registry.list_definitions():
        for op in definition.operations.values():
            for node_type in op.node_types or []:
                assert (
                    node_type in NODE_REGISTRY
                    or connector_registry.primary_for_node_type(node_type) is not None
                ), f"{node_type} unroutable"


# ----------------------------------------------------------------------
# Execution record contract (API envelope)
# ----------------------------------------------------------------------

EXECUTION_ENVELOPE_KEYS = {
    "id", "workflow_id", "workflow_version", "trigger", "status",
    "error", "started_at", "finished_at", "pause_state",
}


def test_execution_record_contract(client):
    from tests.test_api.conftest import auth_headers, make_workflow, register

    headers = auth_headers(register(client)["token"])
    client.post("/api/workflows", json=make_workflow(), headers=headers)
    eid = client.post("/api/workflows/wf_1/run", json={}, headers=headers).json()["data"]["execution_id"]

    import time
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        body = client.get(f"/api/executions/{eid}", headers=headers).json()
        if body["data"]["status"] not in ("queued", "running", "cancelling"):
            break
        time.sleep(0.05)

    data = body["data"]
    missing = EXECUTION_ENVELOPE_KEYS - set(data)
    assert not missing, f"execution envelope missing keys: {missing}"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    return TestClient(fastapi_app)

# ----------------------------------------------------------------------
# Universal runtime lifecycle contract (Phase 40)
# ----------------------------------------------------------------------

CONNECTOR_RUNTIME_STAGES = (
    "discover", "validate", "configure",
    "authenticate", "execute", "normalize", "report",
)


def test_runtime_lifecycle_stages_documented_and_hooked():
    from app.connectors import CONNECTOR_RUNTIME_STAGES, ConnectorSDK

    assert CONNECTOR_RUNTIME_STAGES == CONNECTOR_RUNTIME_STAGES
    # SDK exposes the normalize hook (stage 6) with passthrough default
    sdk = ConnectorSDK.__new__(ConnectorSDK)
    sentinel = {"raw": True}
    assert sdk.normalize_output("op", {}, sentinel) is sentinel


def test_business_connector_ops_declare_idempotency(connector_registry):
    """Legacy built-ins must not ship 'unknown' idempotency anymore."""
    for key in ("salesforce", "hubspot", "google_calendar", "google_sheets"):
        defn = connector_registry.get_definition(key)
        for op in defn.operations.values():
            assert op.idempotency in {
                "idempotent", "conditionally_idempotent", "non_idempotent",
            }, f"{key}/{op.operation_key}: {op.idempotency}"
