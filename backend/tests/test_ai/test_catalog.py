"""Phase 15 — planner catalog grounding.

The prompt is built from live registries: every node type it offers
exists in NODE_REGISTRY, every connector/operation exists in the
ConnectorRegistry. Rendering is deterministic.
"""

from __future__ import annotations

import pytest

from app.ai.catalog import build_connector_entries, build_node_entries, render_system_prompt
from app.connectors import get_registry, register_builtin_connectors
from app.nodes.registry import NODE_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _connectors():
    registry = get_registry()
    if not registry.is_initialized():
        registry.initialize()
    register_builtin_connectors()


def test_catalog_offers_only_real_node_types():
    for entry in build_node_entries():
        assert entry["type"] in NODE_REGISTRY


def test_catalog_covers_the_real_registry():
    entries = {e["type"] for e in build_node_entries()}
    assert entries == set(NODE_REGISTRY)
    assert "http_request" in entries and "manual_trigger" in entries


def test_parameter_schemas_are_real():
    by_type = {e["type"]: e for e in build_node_entries()}
    # http_request really has method/url; salesforce_trigger has polling params.
    assert "method" in by_type["http_request"]["parameters"]
    assert "url" in by_type["http_request"]["parameters"]
    assert by_type["manual_trigger"]["trigger"] is True
    assert by_type["http_request"]["trigger"] is False


def test_connector_operations_are_ground_truth():
    entries = {e["connector"]: e for e in build_connector_entries()}
    sf = entries.get("salesforce")
    assert sf is not None
    assert {"search", "get", "create", "update", "upsert", "delete", "query"} <= set(sf["operations"])
    assert sf["credential_types"] == ["salesforce"]
    # Required fields come from the definition's input_schema.
    assert set(sf["operations"]["create"]["parameters"]) >= {"object_name", "record"}
    assert sf["operations"]["create"]["parameters"]["object_name"].get("required") is True


def test_system_prompt_is_deterministic_and_grounded():
    a = render_system_prompt()
    b = render_system_prompt()
    assert a == b  # byte-identical across calls
    assert "salesforce" in a
    assert "http_request" in a
    # The anti-invention contract is stated in the prompt itself.
    assert "NEVER invent" in a
