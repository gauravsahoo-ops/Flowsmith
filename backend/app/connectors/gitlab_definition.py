"""GitLab connector definition (Batch B, original)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

GITLAB_CONNECTOR_KEY = "gitlab"
GITLAB_CONNECTOR_VERSION = "1.0.0"
GITLAB_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=GITLAB_CONNECTOR_KEY,
        connector_version=GITLAB_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=GITLAB_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="gitlab",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["gitlab"],
    )


def build_gitlab_definition() -> ConnectorDefinitionV1:
    pid = {"project_id": {"type": "string", "title": "Project id or path"}}
    return ConnectorDefinitionV1(
        connector_key=GITLAB_CONNECTOR_KEY,
        display_name="GitLab",
        description="Work with GitLab projects, issues, notes, and merge requests.",
        category="developer",
        connector_version=GITLAB_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_issues": _operation(
                "list_issues", "List Issues", "List project issues.", pid, ["project_id"],
            ),
            "get_issue": _operation(
                "get_issue", "Get Issue", "Fetch one issue by IID.",
                {**pid, "issue_iid": {"type": "string", "title": "Issue IID"}}, ["project_id", "issue_iid"],
            ),
            "create_issue": _operation(
                "create_issue", "Create Issue", "Create a project issue.",
                {
                    **pid,
                    "title": {"type": "string", "title": "Title"},
                    "description": {"type": "string", "title": "Description"},
                },
                ["project_id", "title"], retryable=False, idempotency="non_idempotent",
            ),
            "add_note": _operation(
                "add_note", "Add Note", "Comment on an issue.",
                {
                    **pid,
                    "issue_iid": {"type": "string", "title": "Issue IID"},
                    "body": {"type": "string", "title": "Note body"},
                },
                ["project_id", "issue_iid", "body"], retryable=False, idempotency="non_idempotent",
            ),
            "list_merge_requests": _operation(
                "list_merge_requests", "List Merge Requests", "List open merge requests.", pid, ["project_id"],
            ),
        },
        triggers={},
        credential_types={
            "gitlab": CredentialTypeV1(
                type_key="gitlab",
                display_name="GitLab",
                description="GitLab personal access token (+ optional self-hosted https host).",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "access_token": {"type": "string", "title": "Personal access token"},
                        "host": {"type": "string", "title": "Host (default https://gitlab.com)"},
                    },
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_issues", "get_issue", "create_issue", "add_note", "list_merge_requests"], "auth": "PAT"},
        icon="🦊",
    )
