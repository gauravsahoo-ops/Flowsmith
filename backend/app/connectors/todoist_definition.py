"""Todoist connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

TODOIST_CONNECTOR_KEY = "todoist"
TODOIST_CONNECTOR_VERSION = "1.0.0"
TODOIST_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=TODOIST_CONNECTOR_KEY,
        connector_version=TODOIST_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=TODOIST_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="todoist",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["todoist"],
    )


def build_todoist_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=TODOIST_CONNECTOR_KEY,
        display_name="Todoist",
        description="Manage Todoist tasks and comments.",
        category="productivity",
        connector_version=TODOIST_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_tasks": _operation(
                "list_tasks", "List Tasks", "List tasks.",
                {"limit": {"type": "integer", "title": "Limit"}}, [],
            ),
            "get_task": _operation(
                "get_task", "Get Task", "Fetch one task by id.",
                {"task_id": {"type": "string", "title": "Task id"}}, ["task_id"],
            ),
            "create_task": _operation(
                "create_task", "Create Task", "Create a task.",
                {
                    "content": {"type": "string", "title": "Content"},
                    "description": {"type": "string", "title": "Description"},
                },
                ["content"], retryable=False, idempotency="non_idempotent",
            ),
            "update_task": _operation(
                "update_task", "Update Task", "Update content/description.",
                {
                    "task_id": {"type": "string", "title": "Task id"},
                    "content": {"type": "string", "title": "Content"},
                    "description": {"type": "string", "title": "Description"},
                },
                ["task_id"],
            ),
            "close_task": _operation(
                "close_task", "Close Task", "Mark a task complete.",
                {"task_id": {"type": "string", "title": "Task id"}}, ["task_id"],
                retryable=False, idempotency="non_idempotent",
            ),
            "add_comment": _operation(
                "add_comment", "Add Comment", "Comment on a task.",
                {
                    "task_id": {"type": "string", "title": "Task id"},
                    "content": {"type": "string", "title": "Comment text"},
                },
                ["task_id", "content"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "todoist": CredentialTypeV1(
                type_key="todoist",
                display_name="Todoist",
                description="Todoist personal API token (Settings > Integrations).",
                secret_fields=["api_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"api_token": {"type": "string", "title": "API token"}},
                    "required": ["api_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_tasks", "get_task", "create_task", "update_task", "close_task", "add_comment"], "auth": "API token"},
        icon="☑️",
    )
