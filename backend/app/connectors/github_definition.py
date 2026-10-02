"""GitHub connector definition (Phase 11 business connectors).

REST v3 operations over a personal-access-token credential:

1. get_repo     - repository summary
2. create_issue - open an issue (labels supported)
3. add_comment  - comment on an issue or PR
4. list_issues  - page through issues (per_page/page pagination)
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

GITHUB_CONNECTOR_KEY = "github"
GITHUB_CONNECTOR_VERSION = "1.0.0"
GITHUB_OPERATION_VERSION = "1.0.0"


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
        connector_key=GITHUB_CONNECTOR_KEY,
        connector_version=GITHUB_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=GITHUB_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="github",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["github"],
    )


_OWNER = {"type": "string", "title": "Owner (user/org)"}
_REPO = {"type": "string", "title": "Repository name"}


def _github_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "get_repo": _operation(
            "get_repo", "Get Repository",
            "Fetch summary metadata for one repository.",
            {"owner": _OWNER, "repo": _REPO},
            ["owner", "repo"],
            {
                "type": "object",
                "properties": {
                    "full_name": {"type": "string"},
                    "default_branch": {"type": "string"},
                    "stars": {"type": "integer"},
                },
            },
            retryable=True,
        ),
        "create_issue": _operation(
            "create_issue", "Create Issue",
            "Open a new issue with optional body and labels.",
            {
                "owner": _OWNER, "repo": _REPO,
                "title": {"type": "string", "title": "Issue title"},
                "body": {"type": "string", "title": "Issue body"},
                "labels": {"type": "array", "title": "Labels", "items": {"type": "string"}},
            },
            ["owner", "repo", "title"],
            {
                "type": "object",
                "properties": {"number": {"type": "integer"}, "url": {"type": "string"}},
            },
            retryable=False,
            idempotency="non_idempotent",
        ),
        "add_comment": _operation(
            "add_comment", "Add Comment",
            "Comment on an issue or pull request.",
            {
                "owner": _OWNER, "repo": _REPO,
                "issue_number": {"type": "integer", "title": "Issue/PR number"},
                "body": {"type": "string", "title": "Comment body"},
            },
            ["owner", "repo", "issue_number", "body"],
            {"type": "object", "properties": {"comment_id": {"type": "integer"}}},
            retryable=False,
            idempotency="non_idempotent",
        ),
        "list_issues": _operation(
            "list_issues", "List Issues",
            "List issues of one repository (paginated; PRs flagged).",
            {
                "owner": _OWNER, "repo": _REPO,
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "per_page": {"type": "integer", "title": "Page size", "default": 50, "minimum": 1, "maximum": 100},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 10},
            },
            ["owner", "repo"],
            {"type": "object", "properties": {"issues": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
    }


def _github_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "github": CredentialTypeV1(
            type_key="github",
            display_name="GitHub",
            description=(
                "GitHub access token — a classic PAT or fine-grained token with "
                "the repo scopes your workflows need."
            ),
            secret_fields=["access_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "title": "Access token (ghp_… / github_pat_…)"},
                    "login": {"type": "string", "title": "Account login (display)"},
                },
                "required": ["access_token"],
            },
            encryption_required=True,
        )
    }


def build_github_definition() -> ConnectorDefinitionV1:
    """Build the GitHub connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=GITHUB_CONNECTOR_KEY,
        display_name="GitHub",
        description="Inspect repositories and manage issues on GitHub via REST v3.",
        category="developer",
        connector_version=GITHUB_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_github_operations(),
        triggers={},
        credential_types=_github_credential_type(),
        metadata={
            "initial_operations": ["get_repo", "create_issue", "add_comment", "list_issues"],
            "auth": "personal access token",
            "rate_limits": "primary+secondary budgets honored (X-RateLimit headers)",
        },
        icon="github",
    )
