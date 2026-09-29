"""Box connector definition (Phase 39)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

BOX_CONNECTOR_KEY = "box"
BOX_CONNECTOR_VERSION = "1.0.0"
BOX_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=BOX_CONNECTOR_KEY,
        connector_version=BOX_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=BOX_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="box",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["box"],
    )


def build_box_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=BOX_CONNECTOR_KEY,
        display_name="Box",
        description="Manage enterprise files, folders, and full-text search with Box Cloud Content Management.",
        category="storage",
        connector_version=BOX_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_folder_items": _operation(
                "list_folder_items", "List Folder Items", "List files and subfolders in a Box folder.",
                {
                    "folder_id": {"type": "string", "title": "Folder ID", "default": "0"},
                    "limit": {"type": "integer", "title": "Limit", "default": 100},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                },
                [],
            ),
            "get_file": _operation(
                "get_file", "Get File Metadata", "Retrieve metadata and details for a file in Box.",
                {
                    "file_id": {"type": "string", "title": "File ID"},
                },
                ["file_id"],
            ),
            "create_folder": _operation(
                "create_folder", "Create Folder", "Create a new folder in Box.",
                {
                    "name": {"type": "string", "title": "Folder Name"},
                    "parent_id": {"type": "string", "title": "Parent Folder ID", "default": "0"},
                },
                ["name"],
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_file": _operation(
                "delete_file", "Delete File", "Delete a file or move it to trash in Box.",
                {
                    "file_id": {"type": "string", "title": "File ID"},
                },
                ["file_id"],
                retryable=False, idempotency="idempotent",
            ),
            "search": _operation(
                "search", "Search Files & Folders", "Search for files and folders across Box content.",
                {
                    "query": {"type": "string", "title": "Search Query"},
                    "limit": {"type": "integer", "title": "Limit", "default": 30},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                    "type_filter": {"type": "string", "title": "Type Filter (file, folder, web_link)"},
                },
                ["query"],
            ),
            "upload_file": _operation(
                "upload_file", "Upload File", "Upload a new file to a Box folder.",
                {
                    "name": {"type": "string", "title": "File Name"},
                    "content": {"type": "string", "title": "File Content (text or base64)"},
                    "parent_id": {"type": "string", "title": "Parent Folder ID", "default": "0"},
                },
                ["name", "content"],
                retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={
            "webhook": ConnectorTriggerV1(
                connector_key=BOX_CONNECTOR_KEY,
                connector_version=BOX_CONNECTOR_VERSION,
                trigger_key="webhook",
                trigger_version="1.0.0",
                trigger_type="webhook",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "events": {"type": "array", "items": {"type": "string"}, "title": "Target Event Types"},
                    },
                },
                credential_require="box",
                node_types=["box"],
            )
        },
        credential_types={
            "box": CredentialTypeV1(
                type_key="box",
                display_name="Box Access Token",
                description="Box Developer token or OAuth 2.0 access token.",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "access_token": {"type": "string", "title": "Access Token"},
                    },
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
    )
