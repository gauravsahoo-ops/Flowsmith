"""Regression tests for canonical connector/node display names."""

from __future__ import annotations

from collections import Counter

import pytest

from app.api.nodes import _connector_catalog_entries
from app.connectors import get_registry, register_builtin_connectors
from app.connectors.naming import is_hidden_in_catalog
from app.nodes.registry import NODE_REGISTRY, list_nodes


@pytest.fixture(autouse=True)
def _names_ready():
    register_builtin_connectors()


FORBIDDEN_NAMES = {
    "Background Color",
    "Limit Wait Time",
    "Timeout",
    "Document",
    "Extraction Values",
    "Workflow Inputs",
    "AwsS3",
    "E2E Test",
    "E2E Test Polling Trigger",
}


def test_visible_connector_names_are_canonical_and_unique():
    registry = get_registry()
    visible = [
        d for d in registry.list_definitions()
        if not is_hidden_in_catalog(d.connector_key)
    ]
    names = [d.display_name.strip().lower() for d in visible]
    assert not [name for name, count in Counter(names).items() if count > 1]
    assert not [d.display_name for d in visible if d.display_name in FORBIDDEN_NAMES]


def test_catalog_names_are_unique_and_do_not_expose_internal_entries():
    catalog = list_nodes() + _connector_catalog_entries()
    names = [entry["display_name"].strip().lower() for entry in catalog]
    assert not [name for name, count in Counter(names).items() if count > 1]
    assert not [entry["display_name"] for entry in catalog if entry["display_name"] in FORBIDDEN_NAMES]
    types = {entry["type"] for entry in catalog}
    assert "e2e_test" not in types
    assert "e2e_test_polling_trigger" not in types
    assert "active_campaign" not in types


def test_known_alias_and_label_fixes():
    registry = get_registry()
    assert registry.get_definition("active_campaign") is not None
    assert is_hidden_in_catalog("active_campaign")
    assert registry.get_definition("activecampaign").display_name == "ActiveCampaign"
    assert registry.get_definition("slack").display_name == "Slack API"
    assert NODE_REGISTRY["split"].display_name == "Split Out (Legacy)"
    assert NODE_REGISTRY["split_out"].display_name == "Split Out"


def test_generated_and_trigger_operation_labels_are_readable_and_unique():
    registry = get_registry()
    for definition in registry.list_definitions():
        labels = [op.display_name for op in definition.operations.values()]
        assert len(labels) == len(set(labels)), definition.connector_key
        assert all(label and label == label.strip() for label in labels), definition.connector_key

    assert registry.get_definition("databricks_trigger").operations["runstarted"].display_name == "Run Started"
    assert registry.get_definition("frankfurter").operations["get_start_date"].display_name == "Get rates for a start date"
    assert registry.get_definition("httpbin").operations["delete_anything"].display_name == "Delete Anything"
