"""Google Drive connector definition (Phase 11 business connectors).

Drive v3 operations over the shared Google OAuth app:

1. list_files  - list (folder) files, nextPageToken pagination
2. upload_file - create a file with text/base64 content
3. get_file    - fetch file metadata
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

GOOGLE_DRIVE_CONNECTOR_KEY = "google_drive"
GOOGLE_DRIVE_CONNECTOR_VERSION = "1.0.0"
GOOGLE_DRIVE_OPERATION_VERSION = "1.0.0"


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
        connector_key=GOOGLE_DRIVE_CONNECTOR_KEY,
        connector_version=GOOGLE_DRIVE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=GOOGLE_DRIVE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="google_drive",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["google_drive"],
    )


_FOLDER_ID = {
    "type": "string", "title": "Folder id",
    "description": "Optional Drive folder id; empty lists the root.",
}
_TIMEOUT_PROP = {"type": "number", "title": "Timeout (seconds)", "default": 30, "minimum": 1}


def _google_drive_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "list_files": _operation(
            "list_files", "List Files",
            "List Drive files (inside a folder when given), newest first.",
            {
                "folder_id": _FOLDER_ID,
                "page_size": {"type": "integer", "title": "Page size", "default": 50, "minimum": 1, "maximum": 100},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 20},
                "query_extra": {"type": "string", "title": "Extra query clauses", "description": "Appended to the q filter."},
                "timeout_seconds": _TIMEOUT_PROP,
            },
            [],
            {
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
        "upload_file": _operation(
            "upload_file", "Upload File",
            "Create a Drive file from text or base64 content.",
            {
                "name": {"type": "string", "title": "File name"},
                "content": {"type": "string", "title": "Content"},
                "mime_type": {"type": "string", "title": "MIME type", "default": "text/plain"},
                "folder_id": _FOLDER_ID,
                "is_base64": {"type": "boolean", "title": "Content is base64", "default": False},
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["name", "content"],
            {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "name": {"type": "string"},
                    "success": {"type": "boolean"},
                },
            },
            retryable=False,
            idempotency="non_idempotent",
        ),
        "get_file": _operation(
            "get_file", "Get File",
            "Fetch metadata for one Drive file.",
            {"file_id": {"type": "string", "title": "File id"}, "timeout_seconds": _TIMEOUT_PROP},
            ["file_id"],
            {"type": "object", "properties": {"file": {"type": "object"}}},
            retryable=True,
        ),
    }


def _google_drive_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "google_drive": CredentialTypeV1(
            type_key="google_drive",
            display_name="Google Drive",
            description=(
                "Google Drive connection. Prefer 'Connect Google Drive' in the UI: "
                "the refresh token is stored encrypted and access tokens are minted "
                "server-side on demand."
            ),
            secret_fields=["refresh_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "user": {"type": "string", "title": "Authorizing account email (display)"},
                    "refresh_token": {"type": "string", "title": "Refresh Token ('Connect Google Drive')"},
                    "oauth": {"type": "boolean", "title": "OAuth-connected", "default": False},
                },
            },
            encryption_required=True,
        )
    }


def build_google_drive_definition() -> ConnectorDefinitionV1:
    """Build the Google Drive connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=GOOGLE_DRIVE_CONNECTOR_KEY,
        display_name="Google Drive",
        description="List, inspect and create Google Drive files via the Drive v3 API.",
        category="api",
        connector_version=GOOGLE_DRIVE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_google_drive_operations(),
        triggers={},
        credential_types=_google_drive_credential_type(),
        metadata={
            "initial_operations": ["list_files", "upload_file", "get_file"],
            "auth": "OAuth2 (Connect Google Drive)",
        },
        icon="🚗",
    )
