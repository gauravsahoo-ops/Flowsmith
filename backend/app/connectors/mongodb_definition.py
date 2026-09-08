"""MongoDB connector definition (Phase 11 business connectors).

1. find       - query documents (skip/limit)
2. insert_one - add a document
3. update_one - patch one document ($set shorthand supported)
4. delete_one - remove one document
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

MONGODB_CONNECTOR_KEY = "mongodb"
MONGODB_CONNECTOR_VERSION = "1.0.0"
MONGODB_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: dict,
    required: list[str],
    output_schema: dict,
    *,
    retryable: bool = False,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=MONGODB_CONNECTOR_KEY,
        connector_version=MONGODB_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=MONGODB_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="mongodb",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["mongodb"],
    )


_DB = {"type": "string", "title": "Database"}
_COLL = {"type": "string", "title": "Collection"}


def _mongodb_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "find": _operation(
            "find", "Find Documents",
            "Query documents with a filter (skip/limit paging).",
            {
                "database": _DB, "collection": _COLL,
                "filter": {"type": "object", "title": "Filter"},
                "limit": {"type": "integer", "title": "Limit", "default": 50, "minimum": 1, "maximum": 500},
                "skip": {"type": "integer", "title": "Skip", "default": 0, "minimum": 0},
            },
            ["database", "collection"],
            {"type": "object", "properties": {"documents": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
        "insert_one": _operation(
            "insert_one", "Insert Document",
            "Insert one document.",
            {
                "database": _DB, "collection": _COLL,
                "document": {"type": "object", "title": "Document"},
            },
            ["database", "collection", "document"],
            {"type": "object", "properties": {"inserted_id": {"type": "string"}, "success": {"type": "boolean"}}},
            retryable=False,
            idempotency="non_idempotent",
        ),
        "update_one": _operation(
            "update_one", "Update Document",
            "Update the first document matching a filter.",
            {
                "database": _DB, "collection": _COLL,
                "filter": {"type": "object", "title": "Filter"},
                "update": {"type": "object", "title": "Update expression or plain fields"},
            },
            ["database", "collection", "filter", "update"],
            {"type": "object", "properties": {"matched": {"type": "integer"}, "modified": {"type": "integer"}}},
            retryable=True,
        ),
        "delete_one": _operation(
            "delete_one", "Delete Document",
            "Delete the first document matching a filter.",
            {
                "database": _DB, "collection": _COLL,
                "filter": {"type": "object", "title": "Filter"},
            },
            ["database", "collection", "filter"],
            {"type": "object", "properties": {"deleted": {"type": "integer"}}},
            retryable=True,
            idempotency="conditionally_idempotent",
        ),
    }


def _mongodb_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "mongodb": CredentialTypeV1(
            type_key="mongodb",
            display_name="MongoDB",
            description=(
                "MongoDB connection URI (mongodb:// or mongodb+srv://). Stored "
                "encrypted; needs the 'pymongo' package installed on the server."
            ),
            secret_fields=["uri"],
            validation_schema={
                "type": "object",
                "properties": {
                    "uri": {"type": "string", "title": "Connection URI"},
                },
                "required": ["uri"],
            },
            encryption_required=True,
        )
    }


def build_mongodb_definition() -> ConnectorDefinitionV1:
    """Build the MongoDB connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=MONGODB_CONNECTOR_KEY,
        display_name="MongoDB",
        description="Find and modify documents in MongoDB collections.",
        category="database",
        connector_version=MONGODB_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_mongodb_operations(),
        triggers={},
        credential_types=_mongodb_credential_type(),
        metadata={
            "initial_operations": ["find", "insert_one", "update_one", "delete_one"],
            "auth": "connection URI stored encrypted",
        },
        icon="🍃",
    )
