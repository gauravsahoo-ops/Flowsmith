"""Asana connector definition (Batch B, original)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

ASANA_CONNECTOR_KEY = "asana"
ASANA_CONNECTOR_VERSION = "1.0.0"
ASANA_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=ASANA_CONNECTOR_KEY,
        connector_version=ASANA_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=ASANA_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="asana",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["asana"],
    )


def build_asana_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=ASANA_CONNECTOR_KEY,
        display_name="Asana",
        description="Work with Asana projects, tasks, and comments.",
        category="productivity",
        connector_version=ASANA_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_tasks": _operation(
                "list_tasks", "List Project Tasks", "List tasks in a project.",
                {"project_id": {"type": "string", "title": "Project id"}}, ["project_id"],
            ),
            "get_task": _operation(
                "get_task", "Get Task", "Fetch one task by id.",
                {"task_id": {"type": "string", "title": "Task id"}}, ["task_id"],
            ),
            "create_task": _operation(
                "create_task", "Create Task", "Create a task in a project.",
                {
                    "project_id": {"type": "string", "title": "Project id"},
                    "name": {"type": "string", "title": "Task name"},
                    "notes": {"type": "string", "title": "Notes"},
                },
                ["project_id", "name"], retryable=False, idempotency="non_idempotent",
            ),
            "update_task": _operation(
                "update_task", "Update Task", "Update name/notes/due date/assignee.",
                {
                    "task_id": {"type": "string", "title": "Task id"},
                    "name": {"type": "string", "title": "Name"},
                    "notes": {"type": "string", "title": "Notes"},
                    "due_on": {"type": "string", "title": "Due date YYYY-MM-DD"},
                    "assignee": {"type": "string", "title": "Assignee user id"},
                },
                ["task_id"],
            ),
            "add_comment": _operation(
                "add_comment", "Add Comment", "Add a story comment to a task.",
                {
                    "task_id": {"type": "string", "title": "Task id"},
                    "text": {"type": "string", "title": "Comment text"},
                },
                ["task_id", "text"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "asana": CredentialTypeV1(
                type_key="asana",
                display_name="Asana",
                description="Asana personal access token (My Profile Settings > Apps).",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"access_token": {"type": "string", "title": "Personal access token"}},
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_tasks", "get_task", "create_task", "update_task", "add_comment"], "auth": "PAT Bearer"},
        icon="asana",
    )
