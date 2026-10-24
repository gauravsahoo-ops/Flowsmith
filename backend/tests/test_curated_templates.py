"""Focused guarantees for the curated multi-step business templates."""

from __future__ import annotations


def test_curated_templates_are_multi_step_and_parameter_complete():
    import app.nodes  # noqa: F401 - registers built-in node types
    from app.connectors import get_registry, register_builtin_connectors
    from app.nodes.registry import NODE_REGISTRY
    from app.templates.library import CURATED_BUSINESS_TEMPLATES

    register_builtin_connectors()
    registry = get_registry()
    operations = {
        (node_type, op_key): operation
        for definition in registry.list_definitions()
        for op_key, operation in definition.operations.items()
        for node_type in operation.node_types
    }

    assert len(CURATED_BUSINESS_TEMPLATES) >= 25
    assert {
        "support", "crm", "finance", "devops", "data", "commerce", "people", "knowledge",
    } <= {template["category"] for template in CURATED_BUSINESS_TEMPLATES}

    names = [template["name"] for template in CURATED_BUSINESS_TEMPLATES]
    assert len(names) == len(set(names))

    for template in CURATED_BUSINESS_TEMPLATES:
        nodes = template["workflow_data"]["nodes"]
        assert len(nodes) >= 5, template["name"]
        assert len({node["id"] for node in nodes}) == len(nodes), template["name"]
        assert any(node["id"] == "action" for node in nodes), template["name"]

        for node in nodes:
            node_cls = NODE_REGISTRY.get(node["type"])
            if node_cls is not None:
                node_cls().build_params(node["parameters"])
                continue
            key = (node["type"], node["parameters"].get("operation"))
            operation = operations.get(key)
            assert operation is not None, f"{template['name']} uses unknown operation {key}"
            required = set(operation.input_schema.get("required") or [])
            missing = required - set(node["parameters"])
            assert not missing, f"{template['name']} {key} is missing {sorted(missing)}"
