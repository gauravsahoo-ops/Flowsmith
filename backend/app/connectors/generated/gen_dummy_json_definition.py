"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: DummyJSON
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
)


CONNECTOR_KEY = "dummy_json"
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
        "getcart": _operation("getcart", "Get one cart", "GET /carts/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "getproduct": _operation("getproduct", "Get one product", "GET /products/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "getuser": _operation("getuser", "Get one user", "GET /users/{id}", {"type": "object", "properties": {"id": {"type": "string", "title": "id"}}, "required": ["id"]}),
        "listcarts": _operation("listcarts", "List carts", "GET /carts", {"type": "object", "properties": {}, "required": []}),
        "listposts": _operation("listposts", "List posts", "GET /posts", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}}, "required": []}),
        "listproducts": _operation("listproducts", "List products", "GET /products", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}, "skip": {"type": "string", "title": "skip"}}, "required": []}),
        "listquotes": _operation("listquotes", "List quotes", "GET /quotes", {"type": "object", "properties": {}, "required": []}),
        "listtodos": _operation("listtodos", "List todos", "GET /todos", {"type": "object", "properties": {}, "required": []}),
        "listusers": _operation("listusers", "List users", "GET /users", {"type": "object", "properties": {"limit": {"type": "string", "title": "limit"}}, "required": []}),
        "searchproducts": _operation("searchproducts", "Search products", "GET /products/search", {"type": "object", "properties": {"q": {"type": "string", "title": "q"}}, "required": ["q"]}),
    }


def build_dummy_json_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="DummyJSON",
        description="Generated from DummyJSON.",
        category="developer",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={},
        metadata={"source": "openapi-import", "api_title": "DummyJSON"},
        icon="🧲",
    )
