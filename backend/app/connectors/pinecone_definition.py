"""Pinecone connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

PINECONE_CONNECTOR_KEY = "pinecone"
PINECONE_CONNECTOR_VERSION = "1.0.0"


def build_pinecone_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=PINECONE_CONNECTOR_KEY,
        display_name="Pinecone",
        description="Upsert embeddings, query nearest neighbors, and manage vector indexes in Pinecone.",
        category="database",
        connector_version=PINECONE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        credential_types={
            "pinecone": CredentialTypeV1(
                type_key="pinecone",
                display_name="Pinecone API Key",
                description="Pinecone API key and default index host.",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "required": ["api_key"],
                    "properties": {
                        "api_key": {"type": "string", "title": "API Key", "format": "password"},
                        "host": {"type": "string", "title": "Index Host URL (e.g. index-name-xxx.svc.pinecone.io)"},
                    },
                },
                encryption_required=True,
            )
        },
        operations={
            "upsert_vectors": ConnectorOperationV1(
                connector_key=PINECONE_CONNECTOR_KEY,
                connector_version=PINECONE_CONNECTOR_VERSION,
                operation_key="upsert_vectors",
                operation_version="1.0.0",
                display_name="Upsert Vectors",
                description="Insert or update vector embeddings and metadata in an index.",
                input_schema={
                    "type": "object",
                    "required": ["vectors"],
                    "properties": {
                        "host": {"type": "string", "title": "Index Host"},
                        "vectors": {"type": "array", "title": "Vectors ([{id, values, metadata}])"},
                        "namespace": {"type": "string", "title": "Namespace (Optional)"},
                    },
                },
                output_schema={"type": "object", "properties": {"upsertedCount": {"type": "integer"}}},
                credential_require="pinecone",
                retryable=False,
                idempotency="idempotent",
                node_types=["pinecone"],
            ),
            "query_vectors": ConnectorOperationV1(
                connector_key=PINECONE_CONNECTOR_KEY,
                connector_version=PINECONE_CONNECTOR_VERSION,
                operation_key="query_vectors",
                operation_version="1.0.0",
                display_name="Query Nearest Neighbors",
                description="Search for the most similar vectors by cosine/euclidean/dot-product distance.",
                input_schema={
                    "type": "object",
                    "required": ["vector"],
                    "properties": {
                        "host": {"type": "string", "title": "Index Host"},
                        "vector": {"type": "array", "title": "Query Vector Embedding"},
                        "top_k": {"type": "integer", "title": "Top K", "default": 10},
                        "namespace": {"type": "string", "title": "Namespace (Optional)"},
                        "include_metadata": {"type": "boolean", "title": "Include Metadata", "default": True},
                    },
                },
                output_schema={"type": "object", "properties": {"matches": {"type": "array"}}},
                credential_require="pinecone",
                retryable=True,
                idempotency="idempotent",
                node_types=["pinecone"],
            ),
            "list_indexes": ConnectorOperationV1(
                connector_key=PINECONE_CONNECTOR_KEY,
                connector_version=PINECONE_CONNECTOR_VERSION,
                operation_key="list_indexes",
                operation_version="1.0.0",
                display_name="List Indexes",
                description="List Pinecone indexes in the project.",
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object", "properties": {"indexes": {"type": "array"}}},
                credential_require="pinecone",
                retryable=True,
                idempotency="idempotent",
                node_types=["pinecone"],
            ),
            "delete_vectors": ConnectorOperationV1(
                connector_key=PINECONE_CONNECTOR_KEY,
                connector_version=PINECONE_CONNECTOR_VERSION,
                operation_key="delete_vectors",
                operation_version="1.0.0",
                display_name="Delete Vectors",
                description="Delete vectors by ID or clear a namespace.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "host": {"type": "string", "title": "Index Host"},
                        "ids": {"type": "array", "items": {"type": "string"}, "title": "Vector IDs"},
                        "namespace": {"type": "string", "title": "Namespace (Optional)"},
                        "delete_all": {"type": "boolean", "title": "Delete all vectors", "default": False},
                    },
                },
                output_schema={"type": "object", "properties": {}},
                credential_require="pinecone",
                retryable=False,
                idempotency="non_idempotent",
                node_types=["pinecone"],
            ),
            "describe_index_stats": ConnectorOperationV1(
                connector_key=PINECONE_CONNECTOR_KEY,
                connector_version=PINECONE_CONNECTOR_VERSION,
                operation_key="describe_index_stats",
                operation_version="1.0.0",
                display_name="Describe Index Stats",
                description="Get dimension, total vector count, and per-namespace stats.",
                input_schema={
                    "type": "object",
                    "properties": {"host": {"type": "string", "title": "Index Host"}},
                },
                output_schema={"type": "object", "properties": {"namespaces": {"type": "object"}, "totalVectorCount": {"type": "integer"}}},
                credential_require="pinecone",
                retryable=True,
                idempotency="idempotent",
                node_types=["pinecone"],
            ),
        },
        triggers={},
        metadata={
            "initial_operations": [
                "upsert_vectors", "query_vectors", "list_indexes",
                "delete_vectors", "describe_index_stats",
            ],
            "auth": "API key",
        },
        icon="pinecone",
    )
