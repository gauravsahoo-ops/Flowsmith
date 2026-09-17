"""Dropbox connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

DROPBOX_CONNECTOR_KEY = "dropbox"
DROPBOX_CONNECTOR_VERSION = "1.0.0"
DROPBOX_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=DROPBOX_CONNECTOR_KEY,
        connector_version=DROPBOX_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=DROPBOX_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="dropbox",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["dropbox"],
    )


def build_dropbox_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=DROPBOX_CONNECTOR_KEY,
        display_name="Dropbox",
        description="Browse, manage, and upload Dropbox files.",
        category="storage",
        connector_version=DROPBOX_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_folder": _operation(
                "list_folder", "List Folder", "List entries in a folder.",
                {
                    "path": {"type": "string", "title": "Folder path (empty = root)"},
                    "limit": {"type": "integer", "title": "Limit"},
                },
                [],
            ),
            "get_metadata": _operation(
                "get_metadata", "Get Metadata", "Fetch file/folder metadata.",
                {"path": {"type": "string", "title": "File or folder path"}},
                ["path"],
            ),
            "create_folder": _operation(
                "create_folder", "Create Folder", "Create a folder.",
                {"path": {"type": "string", "title": "New folder path"}},
                ["path"], retryable=False, idempotency="non_idempotent",
            ),
            "delete": _operation(
                "delete", "Delete", "Delete a file or folder.",
                {"path": {"type": "string", "title": "Path to delete"}},
                ["path"], retryable=False, idempotency="non_idempotent",
            ),
            "upload_text": _operation(
                "upload_text", "Upload Text", "Upload/overwrite a small text file.",
                {
                    "path": {"type": "string", "title": "Destination path"},
                    "content": {"type": "string", "title": "Text content"},
                },
                ["path", "content"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "dropbox": CredentialTypeV1(
                type_key="dropbox",
                display_name="Dropbox",
                description="Dropbox OAuth access token (App Console).",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"access_token": {"type": "string", "title": "Access token"}},
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_folder", "get_metadata", "create_folder", "delete", "upload_text"], "auth": "Bearer token"},
        icon="📦",
    )
