"""Node catalog endpoints (spec 9): list types, get parameter schema.

Connector-only node types (no built-in node class) are merged into the
catalog so they are draggable and configurable exactly like node-class
types. Their parameters come from a generic connector operation schema.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user
from app.api.common import ok
from app.connectors import get_registry as _get_connector_registry
from app.models import User
from app.nodes.registry import NODE_REGISTRY, list_nodes

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
            category = "Connectors"
            credential_types = (
                list(definition.credential_types.keys())
                if definition is not None and definition.credential_types
                else []
            )
            idempotency = "conditionally_idempotent"
            operations_meta: dict[str, dict] = {}
            if definition is not None and definition.operations:
                # Phase 9: expose per-operation idempotency/retryable
                # metadata so the UI can show accurate badges instead of
                # a flattened value.
                operations_meta = {
                    op_key: {"idempotency": op.idempotency, "retryable": op.retryable}
                    for op_key, op in definition.operations.items()
                }
                idems = {op.idempotency for op in definition.operations.values()}
                if len(idems) == 1:
                    idempotency = next(iter(idems))
                else:
                    # Mixed operation safety: the node as a whole is only
                    # conditionally safe to re-run (e.g. Salesforce has a
                    # non-idempotent create among idempotent reads).
                    idempotency = "conditionally_idempotent"
            entries.append({
                "type": node_type,
                "version": connector.version,
                "display_name": connector.name,
                "description": connector.description,
                "category": category,
                "icon": "🔌",
                "credential_types": credential_types,
                "input_handles": ["main"],
                "output_handles": ["main"],
                "idempotency": idempotency,
                "operations": operations_meta,
                "parameters_schema": _connector_parameters_schema(connector.connector_id),
            })
    return entries


@router.get("")
def get_nodes(user: User = Depends(get_current_user)) -> dict:
    return ok(list_nodes() + _connector_catalog_entries())


@router.get("/{node_type}/schema")
def get_node_schema(node_type: str, user: User = Depends(get_current_user)) -> dict:
    node_cls = NODE_REGISTRY.get(node_type)
    if node_cls is not None:
        return ok(node_cls.parameters_schema.model_json_schema())
    for entry in _connector_catalog_entries():
        if entry["type"] == node_type:
            return ok(entry["parameters_schema"])
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown node type '{node_type}'.")