"""Jira connector definition (Phase 11 business connectors).

Jira Cloud REST v3 operations (email + API token basic auth):

1. search       - JQL search with startAt pagination
2. create_issue - open an issue in a project
3. update_issue - patch issue fields
4. add_comment  - comment on an issue
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

JIRA_CONNECTOR_KEY = "jira"
JIRA_CONNECTOR_VERSION = "1.0.0"
JIRA_OPERATION_VERSION = "1.0.0"


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
        connector_key=JIRA_CONNECTOR_KEY,
        connector_version=JIRA_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=JIRA_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="jira",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["jira"],
    )


def _jira_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "search": _operation(
            "search", "Search (JQL)",
            "Run a JQL query and return matching issues.",
            {
                "jql": {"type": "string", "title": "JQL", "default": "ORDER BY updated DESC"},
                "max_results": {"type": "integer", "title": "Results per page", "default": 50, "minimum": 1, "maximum": 100},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 10},
            },
            ["jql"],
            {"type": "object", "properties": {"issues": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
        "create_issue": _operation(
            "create_issue", "Create Issue",
            "Open an issue in a project (summary + optional description/extra fields).",
            {
                "project_key": {"type": "string", "title": "Project key"},
                "issue_type": {"type": "string", "title": "Issue type", "default": "Task"},
                "summary": {"type": "string", "title": "Summary"},
                "description": {"type": "string", "title": "Description"},
                "fields": {"type": "object", "title": "Extra fields (raw Jira field map)"},
            },
            ["project_key", "summary"],
            {"type": "object", "properties": {"key": {"type": "string"}, "success": {"type": "boolean"}}},
            retryable=False,
            idempotency="non_idempotent",
        ),
        "update_issue": _operation(
            "update_issue", "Update Issue",
            "Patch fields of an existing issue.",
            {
                "issue_key": {"type": "string", "title": "Issue key (e.g. PROJ-123)"},
                "fields": {"type": "object", "title": "Field updates"},
            },
            ["issue_key", "fields"],
            {"type": "object", "properties": {"key": {"type": "string"}, "success": {"type": "boolean"}}},
            retryable=True,
        ),
        "add_comment": _operation(
            "add_comment", "Add Comment",
            "Comment on an issue.",
            {
                "issue_key": {"type": "string", "title": "Issue key"},
                "body": {"type": "string", "title": "Comment text"},
            },
            ["issue_key", "body"],
            {"type": "object", "properties": {"comment_id": {"type": "string"}, "success": {"type": "boolean"}}},
            retryable=False,
            idempotency="non_idempotent",
        ),
    }


def _jira_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "jira": CredentialTypeV1(
            type_key="jira",
            display_name="Jira",
            description=(
                "Jira Cloud connection: your site (https://acme.atlassian.net), "
                "account email and an API token from id.atlassian.com."
            ),
            secret_fields=["api_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "site_url": {"type": "string", "title": "Site URL"},
                    "email": {"type": "string", "title": "Account email"},
                    "api_token": {"type": "string", "title": "API token"},
                },
                "required": ["site_url", "email", "api_token"],
            },
            encryption_required=True,
        )
    }


def build_jira_definition() -> ConnectorDefinitionV1:
    """Build the Jira connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=JIRA_CONNECTOR_KEY,
        display_name="Jira",
        description="Search, create and update Jira Cloud issues via REST v3.",
        category="productivity",
        connector_version=JIRA_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_jira_operations(),
        triggers={},
        credential_types=_jira_credential_type(),
        metadata={
            "initial_operations": ["search", "create_issue", "update_issue", "add_comment"],
            "auth": "basic auth (email + API token)",
        },
        icon="📌",
    )
