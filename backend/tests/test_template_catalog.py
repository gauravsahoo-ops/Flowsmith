"""Built-in template catalog coverage and import-shape validation."""

from __future__ import annotations


def test_template_catalog_has_at_least_fifty_unique_templates():
    from app.api.environments import DEFAULT_TEMPLATES
    from app.templates.library import CONNECTOR_TEMPLATES

    assert len(DEFAULT_TEMPLATES) >= 330
    assert len(CONNECTOR_TEMPLATES) >= 322
    names = [template["name"] for template in DEFAULT_TEMPLATES]
    assert len(names) == len(set(names))


def test_every_connector_template_uses_a_real_connector_operation():
    from app.connectors import get_registry, register_builtin_connectors
    from app.templates.library import CONNECTOR_TEMPLATES

    register_builtin_connectors()
    registry = get_registry()
    valid = {
        (node_type, operation_key)
        for definition in registry.list_definitions()
        for operation_key, operation in definition.operations.items()
        for node_type in (operation.node_types or [])
    }
    for template in CONNECTOR_TEMPLATES:
        nodes = template["workflow_data"]["nodes"]
        action = next(node for node in nodes if node["id"] == "action")
        operation = action["parameters"]["operation"]
        assert (action["type"], operation) in valid, (
            f"{template['name']} references {action['type']}.{operation}, "
            "which is not a registered connector operation"
        )


def test_generated_templates_include_required_operation_parameters():
    from app.connectors import get_registry, register_builtin_connectors
    from app.templates.generated import GENERATED_TEMPLATES

    register_builtin_connectors()
    registry = get_registry()
    operations = {
        (node_type, op_key): operation
        for definition in registry.list_definitions()
        for op_key, operation in definition.operations.items()
        for node_type in operation.node_types
    }
    for template in GENERATED_TEMPLATES:
        action = next(node for node in template["workflow_data"]["nodes"] if node["id"] == "action")
        operation = operations[(action["type"], action["parameters"]["operation"])]
        required = set(operation.input_schema.get("required") or [])
        missing = required - set(action["parameters"])
        assert not missing, f"{template['name']} is missing {sorted(missing)}"


def test_every_template_has_valid_graph_shape():
    from app.api.environments import DEFAULT_TEMPLATES

    for template in DEFAULT_TEMPLATES:
        workflow = template["workflow_data"]
        nodes = workflow["nodes"]
        node_ids = [node["id"] for node in nodes]
        assert len(node_ids) == len(set(node_ids)), template["name"]
        assert workflow["connections"], template["name"]
        for connection in workflow["connections"]:
            assert connection["source"] in node_ids, template["name"]
            assert connection["target"] in node_ids, template["name"]


def test_default_templates_seed_idempotently():
    from app.api.environments import DEFAULT_TEMPLATES, ensure_default_templates
    from app.db import get_session
    from app.models import User, WorkflowTemplate
    from app.security.jwt import hash_password

    db = get_session()
    try:
        user = User(
            email="template-seed@example.com",
            password_hash=hash_password("template-password"),
            role="admin",
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        ensure_default_templates(db, user.id)
        first_count = db.query(WorkflowTemplate).count()
        assert first_count >= len(DEFAULT_TEMPLATES)
        ensure_default_templates(db, user.id)
        assert db.query(WorkflowTemplate).count() == first_count
    finally:
        db.close()
