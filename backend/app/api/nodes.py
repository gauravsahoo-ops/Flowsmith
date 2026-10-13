"""Node catalog endpoints (spec 9): list types, get parameter schema.

Connector-only node types (no built-in node class) are merged into the
catalog so they are draggable and configurable exactly like node-class
types. Their parameters come from a generic connector operation schema.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user
from app.api.common import ok
from app.connectors import get_registry as _get_connector_registry
from app.models import User
from app.nodes.registry import NODE_REGISTRY, list_nodes
from app.parameters import ParameterSchemaBuilder

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


def _connector_operation_enum(connector_key: str) -> list[str]:
    """Operation names advertised for a connector-only node type.

    Derived from the active ConnectorDefinitionV1 in the registry so the
    catalog always matches what discovery reports. Falls back to the
    classic set only when no definition is registered.
    """
    registry = _get_connector_registry()
    if registry.is_initialized():
        definition = registry.get_definition(connector_key)
        if definition is not None and definition.operations:
            return list(definition.operations.keys())
    return ["query", "get", "create", "update", "delete", "list", "describe"]


def _connector_parameters_schema(connector_key: str) -> dict:
    """Parameter schema for a connector-only node type.

    Derived from the active ConnectorDefinitionV1: the operation enum is
    the registered operation set and the remaining properties are the
    union of the operations' input schemas (what op_execute actually
    consumes). Falls back to a generic shape only when no definition is
    registered.
    """
    generic_properties = {
        "operation": {
            "type": "string",
            "enum": _connector_operation_enum(connector_key),
            "title": "Operation",
            "default": "query",
        },
        "soql": {
            "type": "string",
            "title": "SOQL query",
            "default": "SELECT Id, Name FROM Account LIMIT 10",
            "description": "Used by the query operation.",
        },
        "object_name": {
            "type": "string",
            "title": "Object name",
            "default": "Account",
            "description": "Salesforce object API name (get/create/update/delete/describe).",
        },
        "record_id": {"type": "string", "title": "Record Id", "default": "", "description": "Used by get/update/delete."},
        "record": {"type": "object", "title": "Record fields", "default": {}, "description": "Field map for create/update."},
    }
    registry = _get_connector_registry()
    definition = registry.get_definition(connector_key) if registry.is_initialized() else None
    if not definition or not definition.operations:
        return {"type": "object", "properties": generic_properties}

    ops = list(definition.operations.keys())
    properties: dict = {
        "operation": {"type": "string", "enum": ops, "title": "Operation", "default": ops[0]},
    }
    for op in definition.operations.values():
        for name, prop in ((op.input_schema or {}).get("properties") or {}).items():
            if name == "operation" or name in properties:
                continue
            properties[name] = prop
    return {"type": "object", "properties": properties}


def _operations_meta_from_definitions(
    operations: dict[str, Any],
    selector_values: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Normalise declared operations into the shape the parameter builder wants.

    Shared by connector definitions and built-in nodes, which describe their
    operations in slightly different places but identical terms.

    ``selector_values`` is the full set of values the node's selector enum
    accepts. The panel builds its operation dropdown from the returned keys, so
    a declaration that omits one would make that value silently unselectable;
    any gap is filled with a minimal entry marked ``undeclared``.
    """
    meta: dict[str, dict[str, Any]] = {}

    def _record(op_key: str, fields: dict[str, Any]) -> None:
        # Connector definitions nest these under `input_schema`; built-in nodes
        # declare them at the top level. Read whichever is present rather than
        # requiring one spelling, or half the ecosystem silently loses fields.
        schema_block = fields.get("input_schema") or {}
        props = list(fields.get("properties") or schema_block.get("properties") or [])
        required = list(fields.get("required") or schema_block.get("required") or [])
        meta[op_key] = {
            "idempotency": fields.get("idempotency", ""),
            "retryable": fields.get("retryable", False),
            "display_name": fields.get("display_name") or op_key.replace("_", " ").title(),
            "description": fields.get("description", ""),
            "properties": props,
            "required": required,
            "output_preview": fields.get("output_preview") or fields.get("output_schema") or None,
        }

    for op_key, op in operations.items():
        if isinstance(op, dict):
            _record(op_key, op)
            continue
        _record(op_key, {
            "idempotency": getattr(op, "idempotency", ""),
            "retryable": getattr(op, "retryable", False),
            "display_name": getattr(op, "display_name", ""),
            "description": getattr(op, "description", ""),
            "properties": list(((getattr(op, "input_schema", None) or {}).get("properties") or {}).keys()),
            "required": list((getattr(op, "input_schema", None) or {}).get("required", [])),
            "output_preview": getattr(op, "output_schema", None),
        })

    if selector_values:
        declared = set(meta)
        for value in selector_values:
            if value not in declared:
                meta[value] = {
                    "idempotency": "",
                    "retryable": False,
                    "display_name": value.replace("_", " ").title(),
                    "description": "",
                    "properties": [],
                    "required": [],
                    "output_preview": None,
                    # Marks the entry as invented to keep the enum complete.
                    # Undeclared, so the panel never treats it as authoritative.
                    "undeclared": True,
                }
    return meta


def _selector_values(
    source: Any,
    param_schema: dict[str, Any],
    selector: str | None = None,
) -> list[str]:
    """Full set of values the node's selector enum accepts.

    ``param_schema`` is a JSON Schema, so a connector's enum is read straight
    from it. Built-in nodes pass the pydantic field annotation instead, where an
    enum arrives as a ``typing.Literal`` rather than a JSON-schema ``enum``.
    """
    selector = selector or "operation"
    prop = (param_schema or {}).get("properties", {}).get(selector) or {}
    values = prop.get("enum")
    if isinstance(values, list):
        return [str(v) for v in values]

    params_cls = getattr(source, "parameters_schema", None)
    field = getattr(params_cls, "model_fields", {}).get(selector) if params_cls else None
    annotation = getattr(field, "annotation", None) if field else None
    if annotation is None:
        return []
    if hasattr(annotation, "__args__"):
        return [str(a) for a in getattr(annotation, "__args__") if isinstance(a, str)]
    return []


def _connector_catalog_entries() -> list[dict]:
    """Catalog entries for connector-only node types (Phase 23).

    Node classes always win at execution time; connectors only appear
    here for node types with no built-in class.
    """
    entries: list[dict] = []
    registry = _get_connector_registry()
    if not registry.is_initialized():
        from app.connectors import register_builtin_connectors
        register_builtin_connectors()
        registry = _get_connector_registry()
    if not registry.is_initialized():
        return entries
    for connector in registry.list_all():
        definition = registry.get_definition(connector.connector_id)
        for node_type in connector.node_types:
            if node_type in NODE_REGISTRY:
                continue
            def_cat = (definition.category if definition and definition.category else "connectors").lower()
            if def_cat in ("marketing", "content", "seo"):
                category = "Marketing"
            elif def_cat in ("communication",):
                category = "Communication"
            elif def_cat in ("database", "storage"):
                category = "Database"
            elif def_cat in ("crm", "sales", "support", "customer_support"):
                category = "CRM"
            elif def_cat in ("finance", "accounting", "payments"):
                category = "Finance"
            elif def_cat in ("productivity",):
                category = "Productivity"
            elif def_cat in ("developer", "devops"):
                category = "Developer"
            elif def_cat in ("ai",):
                category = "AI"
            elif def_cat in ("transform",):
                category = "Transform"
            elif def_cat in ("logic", "flow"):
                category = "Logic"
            else:
                category = "Connectors"

            credential_types = (
                list(definition.credential_types.keys())
                if definition is not None and definition.credential_types
                else []
            )
            idempotency = "conditionally_idempotent"
            operations_meta: dict[str, dict] = {}
            if definition is not None and definition.operations:
                operations_meta = _operations_meta_from_definitions(definition.operations)
                idems = {op.idempotency for op in definition.operations.values()}
                if len(idems) == 1:
                    idempotency = next(iter(idems))
                else:
                    idempotency = "conditionally_idempotent"

            param_schema = _connector_parameters_schema(connector.connector_id)
            fields = [
                f.model_dump()
                for f in ParameterSchemaBuilder.extract_from_json_schema(param_schema, operations_meta)
            ]

            entries.append({
                "type": node_type,
                "version": connector.version,
                "display_name": connector.name,
                "description": connector.description,
                "category": category,
                "connector_category": def_cat,
                "is_connector": True,
                "icon": "connector",
                "credential_types": credential_types,
                "input_handles": ["main"],
                "output_handles": ["main"],
                "idempotency": idempotency,
                "operations": operations_meta,
                "parameters_schema": param_schema,
                "fields": fields,
            })
    return entries


@router.get("")
def get_nodes(user: User = Depends(get_current_user)) -> dict:
    builtin_nodes = list_nodes()
    # Enrich built-in nodes with schema fields
    enriched_nodes = []
    for node in builtin_nodes:
        node_copy = dict(node)
        schema = node.get("parameters_schema") or {}
        selector = node.get("operation_selector")
        operations_meta = _operations_meta_from_definitions(
            node.get("operations") or {},
            _selector_values(node, schema, selector),
        )
        node_copy["operation_selector"] = selector or "operation"
        node_copy["operations"] = operations_meta
        node_copy["fields"] = [
            f.model_dump()
            for f in ParameterSchemaBuilder.extract_from_json_schema(
                schema, operations_meta, selector=node.get("operation_selector")
            )
        ]
        enriched_nodes.append(node_copy)
    return ok(enriched_nodes + _connector_catalog_entries())


@router.get("/{node_type}/schema")
def get_node_schema(node_type: str, user: User = Depends(get_current_user)) -> dict:
    node_cls = NODE_REGISTRY.get(node_type)
    if node_cls is not None:
        return ok(node_cls.parameters_schema.model_json_schema())
    for entry in _connector_catalog_entries():
        if entry["type"] == node_type:
            return ok(entry["parameters_schema"])
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown node type '{node_type}'.")


@router.get("/{node_type}/parameters")
def get_node_parameters(node_type: str, user: User = Depends(get_current_user)) -> dict:
    """Return enriched parameter fields, operation metadata, and credentials requirements."""
    node_cls = NODE_REGISTRY.get(node_type)
    if node_cls is not None:
        schema = node_cls.parameters_schema.model_json_schema()
        selector = getattr(node_cls, "operation_selector", None)
        operations_meta = _operations_meta_from_definitions(
            getattr(node_cls, "operations", {}) or {},
            _selector_values(node_cls, schema, selector),
        )
        fields = [
            f.model_dump()
            for f in ParameterSchemaBuilder.extract_from_json_schema(
                schema, operations_meta, selector=selector
            )
        ]
        return ok({
            "node_type": node_type,
            "display_name": node_cls.display_name,
            "description": node_cls.description,
            "category": node_cls.category,
            "credential_types": node_cls.credential_types,
            "idempotency": node_cls.idempotency,
            "parameters_schema": schema,
            "operation_selector": selector or "operation",
            "operations": operations_meta,
            "fields": fields,
        })
    for entry in _connector_catalog_entries():
        if entry["type"] == node_type:
            return ok({
                "node_type": node_type,
                "display_name": entry["display_name"],
                "description": entry["description"],
                "category": entry["category"],
                "credential_types": entry["credential_types"],
                "idempotency": entry["idempotency"],
                "parameters_schema": entry["parameters_schema"],
                "operations": entry.get("operations", {}),
                "fields": entry.get("fields", []),
            })
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown node type '{node_type}'.")
