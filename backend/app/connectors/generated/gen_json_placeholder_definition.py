"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: JSONPlaceholder
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
)


CONNECTOR_KEY = "json_placeholder"
CONNECTOR_VERSION = "1.0.0"
OPERATION_VERSION = "1.0.0"


def _operation(key, display_name, description, input_schema, *, retryable=True, idempotency='idempotent'):
    return ConnectorOperationV1(
        connector_key=CONNECTOR_KEY,
        connector_version=CONNECTOR_VERSION,
        operation_key=key,
        operation_version=OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema=input_schema,
        output_schema={"type": "object", "properties": {}},
        credential_require=None,
        retryable=retryable,
        idempotency=idempotency,
        node_types=[CONNECTOR_KEY],
    )


def _operations():
    return {
        "createpost": _operation("createpost", "Create a post", "POST /posts", {"type": "object", "properties": {"body": {"type": "object", "title": "Request body"}}, "required": []}),
        "deletepost": _operation("deletepost", "Delete a post", "DELETE /posts/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "getpost": _operation("getpost", "Get one post", "GET /posts/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "getuser": _operation("getuser", "Get one user", "GET /users/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "listcomments": _operation("listcomments", "List comments", "GET /comments", {"type": "object", "properties": {"postId": {"type": "string", "title": "postId"}}, "required": []}),
        "listposts": _operation("listposts", "List posts", "GET /posts", {"type": "object", "properties": {}, "required": []}),
        "listtodos": _operation("listtodos", "List todos", "GET /todos", {"type": "object", "properties": {}, "required": []}),
        "listusers": _operation("listusers", "List users", "GET /users", {"type": "object", "properties": {}, "required": []}),
        "updatepost": _operation("updatepost", "Replace a post", "PUT /posts/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}, "body": {"type": "object", "title": "Request body"}}, "required": ["id"]}),
    }


def build_json_placeholder_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="JSONPlaceholder",
        description="Generated from JSONPlaceholder.",
        category="developer",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={},
        metadata={"source": "openapi-import", "api_title": "JSONPlaceholder"},
        icon="openapi",
    )
