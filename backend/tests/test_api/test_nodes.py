"""Node catalog tests (spec 9/26.1/35): metadata completeness and the
idempotency declarations every node must make."""

from __future__ import annotations

from app.engine.node_base import CONDITIONALLY_IDEMPOTENT, IDEMPOTENT, NON_IDEMPOTENT
from app.nodes.registry import NODE_REGISTRY, list_nodes


def _by_type():
    return {n["type"]: n for n in list_nodes()}


def test_catalog_exposes_core_metadata():
    for meta in list_nodes():
        for field in (
            "type", "version", "display_name", "description", "category",
            "icon", "credential_types", "input_handles", "output_handles",
            "idempotency", "parameters_schema",
        ):
            assert field in meta, f"{meta['type']} missing {field}"


def test_every_node_declares_a_valid_idempotency_level():
    allowed = {IDEMPOTENT, CONDITIONALLY_IDEMPOTENT, NON_IDEMPOTENT}
    for meta in list_nodes():
        assert meta["idempotency"] in allowed, meta["type"]


def test_pure_local_nodes_are_idempotent():
    catalog = _by_type()
    for node_type in ("manual_trigger", "webhook", "schedule", "set_data", "if_condition"):
        assert catalog[node_type]["idempotency"] == IDEMPOTENT


def test_side_effect_nodes_declare_retry_risk():
    catalog = _by_type()
    assert catalog["send_email"]["idempotency"] == NON_IDEMPOTENT
    assert catalog["ai"]["idempotency"] == NON_IDEMPOTENT
    assert catalog["ai_agent"]["idempotency"] == NON_IDEMPOTENT
    assert catalog["rag_pipeline"]["idempotency"] == NON_IDEMPOTENT
    assert catalog["http_request"]["idempotency"] == CONDITIONALLY_IDEMPOTENT
    assert catalog["database_query"]["idempotency"] == CONDITIONALLY_IDEMPOTENT


def test_resolver_rejects_unknown_node_types():
    assert "definitely_not_a_node" not in NODE_REGISTRY


def test_every_builtin_node_module_is_registered():
    """Every module in app/nodes/ must be wired into the registry
    (regression: websocket was added but never imported)."""
    import importlib
    import pathlib

    modules_dir = pathlib.Path(__file__).resolve().parents[2] / "app" / "nodes"
    modules = {p.stem for p in modules_dir.glob("*.py") if p.stem != "__init__" and p.stem != "registry"}
    for module_name in sorted(modules):
        importlib.import_module(f"app.nodes.{module_name}")
        module = importlib.import_module(f"app.nodes.{module_name}")
        if hasattr(module, "node_type"):
            assert module.node_type in NODE_REGISTRY, f"{module_name} not registered"
    assert "websocket" in NODE_REGISTRY