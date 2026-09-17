"""ClickUp connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

CLICKUP_CONNECTOR_KEY = "clickup"
CLICKUP_CONNECTOR_VERSION = "1.0.0"
CLICKUP_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=CLICKUP_CONNECTOR_KEY,
        connector_version=CLICKUP_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=CLICKUP_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="clickup",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["clickup"],
    )


def build_clickup_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CLICKUP_CONNECTOR_KEY,
        display_name="ClickUp",
        description="Work with ClickUp lists, tasks, and comments.",
        category="productivity",
        connector_version=CLICKUP_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_tasks": _operation(
                "list_tasks", "List Tasks", "List tasks in a list.",
                {
                    "list_id": {"type": "string", "title": "List id"},
                    "limit": {"type": "integer", "title": "Limit"},
                },
                ["list_id"],
            ),
            "get_task": _operation(
                "get_task", "Get Task", "Fetch one task by id.",
                {"task_id": {"type": "string", "title": "Task id"}}, ["task_id"],
            ),
            "create_task": _operation(
                "create_task", "Create Task", "Create a task in a list.",
                {
                    "list_id": {"type": "string", "title": "List id"},
                    "name": {"type": "string", "title": "Task name"},
                    "description": {"type": "string", "title": "Description"},
                    "status": {"type": "string", "title": "Status"},
                },
                ["list_id", "name"], retryable=False, idempotency="non_idempotent",
            ),
            "update_task": _operation(
                "update_task", "Update Task", "Update name/description/status.",
                {
                    "task_id": {"type": "string", "title": "Task id"},
                    "name": {"type": "string", "title": "Task name"},
                    "description": {"type": "string", "title": "Description"},
                    "status": {"type": "string", "title": "Status"},
                },
                ["task_id"],
            ),
            "add_comment": _operation(
                "add_comment", "Add Comment", "Comment on a task.",
                {
                    "task_id": {"type": "string", "title": "Task id"},
                    "comment_text": {"type": "string", "title": "Comment text"},
                },
                ["task_id", "comment_text"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "clickup": CredentialTypeV1(
                type_key="clickup",
                display_name="ClickUp",
                description="ClickUp personal API token (avatar menu > Apps).",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {"api_key": {"type": "string", "title": "API token"}},
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_tasks", "get_task", "create_task", "update_task", "add_comment"], "auth": "API token"},
        icon="✅",
    )
