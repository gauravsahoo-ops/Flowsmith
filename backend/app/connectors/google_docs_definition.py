"""Google Docs connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

GOOGLE_DOCS_CONNECTOR_KEY = "google_docs"
GOOGLE_DOCS_CONNECTOR_VERSION = "1.0.0"
GOOGLE_DOCS_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=GOOGLE_DOCS_CONNECTOR_KEY,
        connector_version=GOOGLE_DOCS_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=GOOGLE_DOCS_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="google_docs",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["google_docs"],
    )


def build_google_docs_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=GOOGLE_DOCS_CONNECTOR_KEY,
        display_name="Google Docs",
        description="Read, create, and edit Google Docs documents.",
        category="productivity",
        connector_version=GOOGLE_DOCS_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "get_document": _operation(
                "get_document", "Get Document", "Fetch a document by id.",
                {"document_id": {"type": "string", "title": "Document id"}}, ["document_id"],
            ),
            "create_document": _operation(
                "create_document", "Create Document", "Create a blank document.",
                {"title": {"type": "string", "title": "Title"}}, ["title"],
                retryable=False, idempotency="non_idempotent",
            ),
            "append_text": _operation(
                "append_text", "Append Text", "Append text at the end of a document.",
                {
                    "document_id": {"type": "string", "title": "Document id"},
                    "text": {"type": "string", "title": "Text to append"},
                },
                ["document_id", "text"], retryable=False, idempotency="non_idempotent",
            ),
            "batch_update": _operation(
                "batch_update", "Batch Update", "Apply raw Docs API requests.",
                {
                    "document_id": {"type": "string", "title": "Document id"},
                    "requests": {"type": "string", "title": "Requests JSON array"},
                },
                ["document_id", "requests"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "google_docs": CredentialTypeV1(
                type_key="google_docs",
                display_name="Google Docs",
                description="Google Docs connection (Connect Google Docs OAuth).",
                secret_fields=["refresh_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "user": {"type": "string", "title": "Authorizing account email"},
                        "refresh_token": {"type": "string", "title": "OAuth2 refresh token"},
                        "oauth": {"type": "boolean", "title": "Created via Connect"},
                    },
                    "required": ["refresh_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["get_document", "create_document", "append_text", "batch_update"], "auth": "OAuth2 (shared Google app)"},
        icon="google_docs",
    )
