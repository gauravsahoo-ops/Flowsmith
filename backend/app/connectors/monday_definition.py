"""Monday.com connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

MONDAY_CONNECTOR_KEY = "monday"
MONDAY_CONNECTOR_VERSION = "1.0.0"
MONDAY_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=MONDAY_CONNECTOR_KEY,
        connector_version=MONDAY_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=MONDAY_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="monday",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["monday"],
    )


def build_monday_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=MONDAY_CONNECTOR_KEY,
        display_name="Monday.com",
        description="Work with Monday.com boards, items, and updates.",
        category="productivity",
        connector_version=MONDAY_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_boards": _operation(
                "list_boards", "List Boards", "List boards.",
                {"limit": {"type": "integer", "title": "Limit"}}, [],
            ),
            "get_board": _operation(
                "get_board", "Get Board", "Fetch one board with groups.",
                {"board_id": {"type": "string", "title": "Board id"}}, ["board_id"],
            ),
            "list_items": _operation(
                "list_items", "List Items", "List items on a board.",
                {
                    "board_id": {"type": "string", "title": "Board id"},
                    "limit": {"type": "integer", "title": "Limit"},
                },
                ["board_id"],
            ),
            "create_item": _operation(
                "create_item", "Create Item", "Create an item on a board.",
                {
                    "board_id": {"type": "string", "title": "Board id"},
                    "group_id": {"type": "string", "title": "Group id (optional)"},
                    "item_name": {"type": "string", "title": "Item name"},
                },
                ["board_id", "item_name"], retryable=False, idempotency="non_idempotent",
            ),
            "add_update": _operation(
                "add_update", "Add Update", "Comment on an item.",
                {
                    "item_id": {"type": "string", "title": "Item id"},
                    "body": {"type": "string", "title": "Update body"},
                },
                ["item_id", "body"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "monday": CredentialTypeV1(
                type_key="monday",
                display_name="Monday.com",
                description="Monday.com API token (avatar menu > Developers).",
                secret_fields=["api_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"api_token": {"type": "string", "title": "API token"}},
                    "required": ["api_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_boards", "get_board", "list_items", "create_item", "add_update"], "auth": "API token"},
        icon="monday",
    )
