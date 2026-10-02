"""Shopify connector definition (Phase 11 business connectors).

Admin REST API operations over a myshopify.com domain + access token:

1. get_product   - one product by numeric id
2. list_products - Link-header page_info pagination
3. create_product- publish a new product
4. get_order     - order summary
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

SHOPIFY_CONNECTOR_KEY = "shopify"
SHOPIFY_CONNECTOR_VERSION = "1.0.0"
SHOPIFY_OPERATION_VERSION = "1.0.0"


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
        connector_key=SHOPIFY_CONNECTOR_KEY,
        connector_version=SHOPIFY_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=SHOPIFY_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="shopify",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["shopify"],
    )


def _shopify_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "get_product": _operation(
            "get_product", "Get Product",
            "Fetch one product with its variants.",
            {"product_id": {"type": "string", "title": "Product id"}},
            ["product_id"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "variants": {"type": "array", "items": {"type": "object"}},
                },
            },
            retryable=True,
        ),
        "list_products": _operation(
            "list_products", "List Products",
            "List products of the store (Link-header pagination).",
            {
                "limit": {"type": "integer", "title": "Page size", "default": 50, "minimum": 1, "maximum": 250},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 10},
                "status": {"type": "string", "enum": ["active", "archived", "draft"], "default": "active"},
            },
            [],
            {"type": "object", "properties": {"products": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
        "create_product": _operation(
            "create_product", "Create Product",
            "Create a product (title required; body, vendor and tags optional).",
            {
                "title": {"type": "string", "title": "Title"},
                "body_html": {"type": "string", "title": "Description HTML"},
                "vendor": {"type": "string", "title": "Vendor"},
                "tags": {"type": "array", "title": "Tags", "items": {"type": "string"}},
            },
            ["title"],
            {"type": "object", "properties": {"id": {"type": "integer"}, "success": {"type": "boolean"}}},
            retryable=False,
            idempotency="non_idempotent",
        ),
        "get_order": _operation(
            "get_order", "Get Order",
            "Fetch summary data for one order.",
            {"order_id": {"type": "string", "title": "Order id"}},
            ["order_id"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "total_price": {"type": "string"},
                    "financial_status": {"type": "string"},
                },
            },
            retryable=True,
        ),
    }


def _shopify_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "shopify": CredentialTypeV1(
            type_key="shopify",
            display_name="Shopify",
            description=(
                "Shopify Admin connection: your store's myshopify.com domain and "
                "an Admin API access token (shpat_…) from a custom app."
            ),
            secret_fields=["access_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "shop_domain": {"type": "string", "title": "Shop domain (acme.myshopify.com)"},
                    "access_token": {"type": "string", "title": "Admin API access token"},
                },
                "required": ["shop_domain", "access_token"],
            },
            encryption_required=True,
        )
    }


def build_shopify_definition() -> ConnectorDefinitionV1:
    """Build the Shopify connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=SHOPIFY_CONNECTOR_KEY,
        display_name="Shopify",
        description="Manage Shopify store products and orders via the Admin REST API.",
        category="finance",
        connector_version=SHOPIFY_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_shopify_operations(),
        triggers={},
        credential_types=_shopify_credential_type(),
        metadata={
            "initial_operations": ["get_product", "list_products", "create_product", "get_order"],
            "auth": "Admin API access token",
            "rate_limits": "leaky-bucket 429 + Retry-After honored",
        },
        icon="shopify",
    )
