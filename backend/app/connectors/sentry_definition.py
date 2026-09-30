"""Sentry connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorCategory,
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

SENTRY_CONNECTOR_KEY = "sentry"
SENTRY_CONNECTOR_VERSION = "1.0.0"


def build_sentry_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=SENTRY_CONNECTOR_KEY,
        display_name="Sentry",
        description="List, inspect, and manage errors and unresolved issues in Sentry.",
        category="developer",
        connector_version=SENTRY_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        credential_types={
            "sentry": CredentialTypeV1(
                type_key="sentry",
                display_name="Sentry Auth Token",
                description="Sentry User Auth Token with project/issue permissions.",
                secret_fields=["auth_token"],
                validation_schema={
                    "type": "object",
                    "required": ["auth_token"],
                    "properties": {
                        "auth_token": {"type": "string", "title": "User Auth Token", "format": "password"},
                        "organization_slug": {"type": "string", "title": "Organization Slug"},
                    },
                },
                encryption_required=True,
            )
        },
        operations={
            "list_issues": ConnectorOperationV1(
                connector_key=SENTRY_CONNECTOR_KEY,
                connector_version=SENTRY_CONNECTOR_VERSION,
                operation_key="list_issues",
                operation_version="1.0.0",
                display_name="List Issues",
                description="Search for unresolved issues in a project or organization.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "organization_slug": {"type": "string", "title": "Organization Slug"},
                        "project_slug": {"type": "string", "title": "Project Slug"},
                        "query": {"type": "string", "title": "Search Query (e.g. is:unresolved)", "default": "is:unresolved"},
                    },
                },
                output_schema={"type": "object", "properties": {"issues": {"type": "array"}}},
                credential_require="sentry",
                retryable=True,
                idempotency="idempotent",
                node_types=["sentry"],
            ),
            "get_issue": ConnectorOperationV1(
                connector_key=SENTRY_CONNECTOR_KEY,
                connector_version=SENTRY_CONNECTOR_VERSION,
                operation_key="get_issue",
                operation_version="1.0.0",
                display_name="Get Issue Details",
                description="Retrieve full stack trace, tags, and metadata for a Sentry issue.",
                input_schema={
                    "type": "object",
                    "required": ["issue_id"],
                    "properties": {
                        "issue_id": {"type": "string", "title": "Issue ID"},
                    },
                },
                output_schema={"type": "object", "properties": {"id": {"type": "string"}}},
                credential_require="sentry",
                retryable=True,
                idempotency="idempotent",
                node_types=["sentry"],
            ),
            "resolve_issue": ConnectorOperationV1(
                connector_key=SENTRY_CONNECTOR_KEY,
                connector_version=SENTRY_CONNECTOR_VERSION,
                operation_key="resolve_issue",
                operation_version="1.0.0",
                display_name="Resolve / Update Issue",
                description="Change issue status (resolved, ignored, unresolved).",
                input_schema={
                    "type": "object",
                    "required": ["issue_id"],
                    "properties": {
                        "issue_id": {"type": "string", "title": "Issue ID"},
                        "status": {"type": "string", "title": "Status (resolved, ignored, unresolved)", "default": "resolved"},
                    },
                },
                output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
                credential_require="sentry",
                retryable=True,
                idempotency="idempotent",
                node_types=["sentry"],
            ),
        },
        triggers={},
    )
