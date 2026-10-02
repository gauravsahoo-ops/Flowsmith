"""Connector discovery + catalog tests: node catalog merges connector-only
node types, discovery endpoints return populated definitions (audit fix)."""

from __future__ import annotations

from app.api.nodes import _connector_catalog_entries
from app.connectors import get_registry, register_builtin_connectors
from tests.test_api.conftest import auth_headers, register


def _setup(client):
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    return auth_headers(register(client)["token"])


def test_catalog_includes_connector_only_node_types():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    entries = {e["type"]: e for e in _connector_catalog_entries()}
    assert "salesforce" in entries
    sf = entries["salesforce"]
    assert sf["display_name"] == "Salesforce"
    assert sf["credential_types"] == ["salesforce"]
    assert sf["icon"] == "connector"
    assert "operation" in sf["parameters_schema"]["properties"]
    # The catalog enum is derived from the registered definition's
    # operation set (Phase 9 full surface incl. upsert/discovery/bulk).
    assert sf["parameters_schema"]["properties"]["operation"]["enum"] == [
        "search", "get", "create", "update", "upsert", "delete",
        "query", "describe", "list", "bulk", "custom_api_call", "flow_invoke",
    ]
    # Phase 9: per-operation idempotency/retryable metadata is exposed.
    assert sf["operations"]["create"]["idempotency"] == "non_idempotent"
    assert sf["operations"]["upsert"]["retryable"] is True


def test_catalog_does_not_shadow_node_classes():
    """Node classes always win: http_request is a node class, so the
    HTTP connector's node type must NOT appear as a connector entry."""
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    entries = {e["type"]: e for e in _connector_catalog_entries()}
    assert "http_request" not in entries


def test_salesforce_definition_discoverable_via_api(client):
    """Phase 6: the explicit definition is what discovery returns."""
    headers = _setup(client)
    resp = client.get("/api/connectors/salesforce", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["connector_version"] == "1.2.0"

    ops = client.get("/api/connectors/salesforce/operations", headers=headers).json()["data"]["operations"]
    assert set(ops.keys()) == {
        "search", "get", "create", "update", "upsert", "delete",
        "query", "describe", "list", "bulk", "custom_api_call", "flow_invoke",
    }
    assert ops["search"]["display_name"] == "Search/Get Record"
    assert ops["search"]["credential_require"] == "salesforce"
    assert ops["create"]["idempotency"] == "non_idempotent"
    assert ops["create"]["retryable"] is False

    creds = client.get("/api/connectors/salesforce/credential-types", headers=headers).json()["data"]["credential_types"]
    assert "salesforce" in creds
    assert creds["salesforce"]["secret_fields"] == ["client_secret", "password", "refresh_token"]


def test_node_catalog_endpoint_includes_connector_types(client):
    headers = _setup(client)
    resp = client.get("/api/nodes", headers=headers)
    assert resp.status_code == 200
    types = {n["type"] for n in resp.json()["data"]}
    assert "salesforce" in types

    schema = client.get("/api/nodes/salesforce/schema", headers=headers)
    assert schema.status_code == 200
    assert "operation" in schema.json()["data"]["properties"]


def test_discovery_returns_populated_connectors(client):
    headers = _setup(client)
    resp = client.get("/api/connectors", headers=headers)
    assert resp.status_code == 200
    by_key = {c["connector_key"]: c for c in resp.json()["data"]}
    assert "salesforce" in by_key
    sf = by_key["salesforce"]
    assert sf["operations"]  # non-empty
    assert sf["credential_types"] == ["salesforce"]

    detail = client.get("/api/connectors/salesforce/operations", headers=headers)
    assert detail.status_code == 200
    assert "query" in detail.json()["data"]["operations"]


def test_trigger_discovery_endpoints(client):
    headers = _setup(client)
    schedule = client.get("/api/connectors/schedule/triggers", headers=headers)
    assert schedule.status_code == 200
    triggers = schedule.json()["data"]["triggers"]
    assert "cron" in triggers
    assert triggers["cron"]["trigger_type"] == "scheduled"
    assert triggers["cron"]["trigger_version"] == "1.0.0"

    webhook = client.get("/api/connectors/webhook/triggers", headers=headers)
    assert webhook.status_code == 200
    assert "receive" in webhook.json()["data"]["triggers"]

    # Connector without triggers -> empty map, not an error.
    http = client.get("/api/connectors/http/triggers", headers=headers)
    assert http.status_code == 200
    assert http.json()["data"]["triggers"] == {}


def test_credential_type_discovery_endpoints(client):
    headers = _setup(client)
    resp = client.get("/api/connectors/salesforce/credential-types", headers=headers)
    assert resp.status_code == 200
    creds = resp.json()["data"]["credential_types"]
    assert "salesforce" in creds
    assert creds["salesforce"]["type_key"] == "salesforce"
    assert "client_secret" in creds["salesforce"]["secret_fields"]
    assert creds["salesforce"]["encryption_required"] is True

    # Connector without credential types -> empty map.
    none = client.get("/api/connectors/schedule/credential-types", headers=headers)
    assert none.status_code == 200
    assert none.json()["data"]["credential_types"] == {}


def test_connector_discovery_404s(client):
    headers = _setup(client)
    assert client.get("/api/connectors/ghost", headers=headers).status_code == 404
    assert client.get("/api/connectors/ghost/operations", headers=headers).status_code == 404
    assert client.get("/api/connectors/ghost/triggers", headers=headers).status_code == 404
    assert client.get("/api/connectors/ghost/credential-types", headers=headers).status_code == 404


def test_connector_detail_has_version_fields(client):
    headers = _setup(client)
    detail = client.get("/api/connectors/salesforce", headers=headers).json()["data"]
    assert detail["connector_version"] == "1.2.0"
    assert detail["lifecycle_status"] == "stable"
    assert detail["operations"]["query"]["operation_version"] == "1.1.0"
    # Phase 10: the Outbound Message event trigger is discoverable.
    assert set(detail["triggers"].keys()) == {"outbound_message"}
    assert detail["triggers"]["outbound_message"]["trigger_type"] == "webhook"
    assert detail["credential_types"]["salesforce"]["type_key"] == "salesforce"


# ----------------------------------------------------------------------
# Authorization
# ----------------------------------------------------------------------

DISCOVERY_PATHS = [
    "/api/connectors",
    "/api/connectors/salesforce",
    "/api/connectors/salesforce/operations",
    "/api/connectors/schedule/triggers",
    "/api/connectors/salesforce/credential-types",
]


def test_discovery_requires_auth(client):
    """Every discovery endpoint rejects unauthenticated requests."""
    for path in DISCOVERY_PATHS:
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} -> {resp.status_code}"


def test_discovery_rejects_invalid_token(client):
    headers = {"Authorization": "Bearer not-a-jwt"}
    for path in DISCOVERY_PATHS:
        resp = client.get(path, headers=headers)
        assert resp.status_code == 401, f"{path} -> {resp.status_code}"


def test_discovery_allows_any_authenticated_user(client):
    """Discovery is read-only: any valid user, not just admins/owners, may list."""
    headers = _setup(client)
    resp = client.get("/api/connectors", headers=headers)
    assert resp.status_code == 200


# ----------------------------------------------------------------------
# Invalid connector keys
# ----------------------------------------------------------------------


def test_invalid_connector_keys_404(client):
    headers = _setup(client)
    for key in ("ghost", "GHOST", "salesforce-v2", "123"):
        for suffix in ("", "/operations", "/triggers", "/credential-types"):
            path = f"/api/connectors/{key}{suffix}"
            assert client.get(path, headers=headers).status_code == 404, path


# ----------------------------------------------------------------------
# Empty registry
# ----------------------------------------------------------------------


def test_empty_registry_returns_empty_list(client):
    """An initialized-but-empty registry yields an empty discovery list,
    not an error."""
    registry = get_registry()
    registry.initialize()  # reset without registering builtins
    headers = auth_headers(register(client)["token"])
    try:
        resp = client.get("/api/connectors", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == []
    finally:
        register_builtin_connectors()  # restore for other tests


def test_empty_registry_keyed_endpoints_404(client):
    """With no connectors registered, keyed discovery endpoints 404."""
    registry = get_registry()
    registry.initialize()
    headers = auth_headers(register(client)["token"])
    try:
        assert client.get("/api/connectors/salesforce", headers=headers).status_code == 404
        assert client.get("/api/connectors/salesforce/operations", headers=headers).status_code == 404
        assert client.get("/api/connectors/schedule/triggers", headers=headers).status_code == 404
        assert client.get("/api/connectors/salesforce/credential-types", headers=headers).status_code == 404
    finally:
        register_builtin_connectors()