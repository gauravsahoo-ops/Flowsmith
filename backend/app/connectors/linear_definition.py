"""Linear connector definition (Batch B, original)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

LINEAR_CONNECTOR_KEY = "linear"
LINEAR_CONNECTOR_VERSION = "1.0.0"
LINEAR_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=LINEAR_CONNECTOR_KEY,
        connector_version=LINEAR_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=LINEAR_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="linear",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["linear"],
    )


def build_linear_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=LINEAR_CONNECTOR_KEY,
        display_name="Linear",
        description="Work with Linear teams, issues, and comments.",
        category="productivity",
        connector_version=LINEAR_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_issues": _operation(
                "list_issues", "List Team Issues", "List issues on a team.",
                {"team_id": {"type": "string", "title": "Team id"}, "limit": {"type": "integer", "title": "Limit"}},
                ["team_id"],
            ),
            "get_issue": _operation(
                "get_issue", "Get Issue", "Fetch one issue by id.",
                {"issue_id": {"type": "string", "title": "Issue id"}}, ["issue_id"],
            ),
            "create_issue": _operation(
                "create_issue", "Create Issue", "Create an issue on a team.",
                {
                    "team_id": {"type": "string", "title": "Team id"},
                    "title": {"type": "string", "title": "Title"},
                    "description": {"type": "string", "title": "Description"},
                },
                ["team_id", "title"], retryable=False, idempotency="non_idempotent",
            ),
            "update_issue": _operation(
                "update_issue", "Update Issue", "Update title/description.",
                {
                    "issue_id": {"type": "string", "title": "Issue id"},
                    "title": {"type": "string", "title": "Title"},
                    "description": {"type": "string", "title": "Description"},
                },
                ["issue_id"],
            ),
            "add_comment": _operation(
                "add_comment", "Add Comment", "Comment on an issue.",
                {
                    "issue_id": {"type": "string", "title": "Issue id"},
                    "body": {"type": "string", "title": "Comment body"},
                },
                ["issue_id", "body"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "linear": CredentialTypeV1(
                type_key="linear",
                display_name="Linear",
                description="Linear API key (Settings > API).",
                secret_fields=["api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {"api_key": {"type": "string", "title": "API key"}},
                    "required": ["api_key"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_issues", "get_issue", "create_issue", "update_issue", "add_comment"], "auth": "API key"},
        icon="linear",
    )
