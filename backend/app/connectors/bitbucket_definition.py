"""Bitbucket connector definition (Batch B, original)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

BITBUCKET_CONNECTOR_KEY = "bitbucket"
BITBUCKET_CONNECTOR_VERSION = "1.0.0"
BITBUCKET_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=BITBUCKET_CONNECTOR_KEY,
        connector_version=BITBUCKET_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=BITBUCKET_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="bitbucket",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["bitbucket"],
    )


def build_bitbucket_definition() -> ConnectorDefinitionV1:
    repo_keys = {
        "workspace": {"type": "string", "title": "Workspace"},
        "repo_slug": {"type": "string", "title": "Repo slug"},
    }
    return ConnectorDefinitionV1(
        connector_key=BITBUCKET_CONNECTOR_KEY,
        display_name="Bitbucket",
        description="Work with Bitbucket workspaces, repos, and pull requests.",
        category="developer",
        connector_version=BITBUCKET_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "list_repos": _operation(
                "list_repos", "List Repos", "List repos in a workspace.",
                {"workspace": {"type": "string", "title": "Workspace"}}, ["workspace"],
            ),
            "get_repo": _operation(
                "get_repo", "Get Repo", "Fetch one repo.",
                repo_keys, ["workspace", "repo_slug"],
            ),
            "list_pull_requests": _operation(
                "list_pull_requests", "List Pull Requests", "List open pull requests.",
                repo_keys, ["workspace", "repo_slug"],
            ),
            "get_pull_request": _operation(
                "get_pull_request", "Get Pull Request", "Fetch one pull request.",
                {**repo_keys, "pr_id": {"type": "string", "title": "PR id"}}, ["workspace", "repo_slug", "pr_id"],
            ),
            "add_comment": _operation(
                "add_comment", "Add Comment", "Comment on a pull request.",
                {
                    **repo_keys,
                    "pr_id": {"type": "string", "title": "PR id"},
                    "text": {"type": "string", "title": "Comment text"},
                },
                ["workspace", "repo_slug", "pr_id", "text"], retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={},
        credential_types={
            "bitbucket": CredentialTypeV1(
                type_key="bitbucket",
                display_name="Bitbucket",
                description="Bitbucket access token (workspace OAuth app or app password token).",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {"access_token": {"type": "string", "title": "Access token"}},
                    "required": ["access_token"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_repos", "get_repo", "list_pull_requests", "get_pull_request", "add_comment"], "auth": "Bearer"},
        icon="bitbucket",
    )
