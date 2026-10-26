"""Native REST connectors for catalog conversion batch 22.

Each connector uses a fixed vendor host, an explicit auth contract, and
operation paths taken from the corresponding n8n node implementation. Keys
whose n8n nodes are local transforms, use the local filesystem, or require an
OAuth2 flow that the shared :class:`~app.connectors.vendor_rest.VendorRESTConnector`
cannot perform are listed in :data:`UNSUPPORTED_BATCH22_KEYS` with the specific
reason instead of being given invented endpoints.

Two operation families are intentionally narrower than their n8n nodes:

* WhatsApp media upload is a multipart binary upload, while the shared
  connector only sends JSON bodies, so the message, media metadata, and media
  delete operations are exposed without the upload operation.
* Zulip reads parameters from form-encoded request bodies and does not parse
  JSON bodies. The shared connector always uses JSON, so the Zulip connector
  exposes the read-only operations whose parameters travel in the query
  string. Write operations are not advertised because they would fail.
"""

from __future__ import annotations

from typing import Any

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)
from app.connectors.vendor_rest import VendorOperation, VendorRESTConnector, VendorSpec


BATCH22_CATALOG_KEYS = frozenset({
    "whats_app",
    "woo_commerce",
    "wordpress",
    "write_binary_file",
    "xml",
    "you_tube",
    "yourls",
    "zulip",
})


VENDOR_SPECS: dict[str, VendorSpec] = {
    "whats_app": VendorSpec(
        key="whats_app",
        display_name="WhatsApp Business Cloud",
        description="WhatsApp Business Cloud messages and media through the Meta Graph API.",
        category="communication",
        base_url="https://graph.facebook.com/v19.0",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "send_message": VendorOperation(
                "send_message", "Send Message", "POST", "/{phone_number_id}/messages",
                ("phone_number_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send a message from a phone number ID. The body must include "
                    "messaging_product, to, type, and the object matching that type."
                ),
            ),
            "send_template": VendorOperation(
                "send_template", "Send Template", "POST", "/{phone_number_id}/messages",
                ("phone_number_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send a template message from a phone number ID. The body must "
                    "include messaging_product, to, type, and a template object with "
                    "name, language, and optional components."
                ),
            ),
            "get_media": VendorOperation(
                "get_media", "Get Media", "GET", "/{media_id}", ("media_id",),
                description="Get the URL and metadata for an uploaded media ID.",
            ),
            "delete_media": VendorOperation(
                "delete_media", "Delete Media", "DELETE", "/{media_id}", ("media_id",),
                description="Delete an uploaded media ID.",
            ),
        },
    ),
    "woo_commerce": VendorSpec(
        key="woo_commerce",
        display_name="WooCommerce",
        description=(
            "WooCommerce customers, products, and orders on a self-hosted store. "
            "Provide the store hostname without a URL scheme."
        ),
        category="ecommerce",
        base_url="https://{host}/wp-json/wc/v3",
        auth_kind="basic",
        basic_user_field="consumer_key",
        basic_password_field="consumer_secret",
        credential_fields=("consumer_key", "consumer_secret"),
        extra_required=("host",),
        operations={
            "create_customer": VendorOperation(
                "create_customer", "Create Customer", "POST", "/customers", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a customer from a WooCommerce customer object.",
            ),
            "delete_customer": VendorOperation(
                "delete_customer", "Delete Customer", "DELETE",
                "/customers/{customer_id}?force=true", ("customer_id",),
            ),
            "get_customer": VendorOperation(
                "get_customer", "Get Customer", "GET", "/customers/{customer_id}",
                ("customer_id",),
            ),
            "list_customers": VendorOperation(
                "list_customers", "List Customers", "GET", "/customers",
                description="List customers; pass filters and per_page as query parameters.",
            ),
            "update_customer": VendorOperation(
                "update_customer", "Update Customer", "PUT", "/customers/{customer_id}",
                ("customer_id",),
                description="Update a customer from a WooCommerce customer object.",
            ),
            "create_order": VendorOperation(
                "create_order", "Create Order", "POST", "/orders", (),
                retryable=False, idempotency="non_idempotent",
                description="Create an order from a WooCommerce order object.",
            ),
            "delete_order": VendorOperation(
                "delete_order", "Delete Order", "DELETE", "/orders/{order_id}?force=true",
                ("order_id",),
            ),
            "get_order": VendorOperation(
                "get_order", "Get Order", "GET", "/orders/{order_id}", ("order_id",),
            ),
            "list_orders": VendorOperation(
                "list_orders", "List Orders", "GET", "/orders",
                description="List orders; pass filters and per_page as query parameters.",
            ),
            "update_order": VendorOperation(
                "update_order", "Update Order", "PUT", "/orders/{order_id}", ("order_id",),
                description="Update an order from a WooCommerce order object.",
            ),
            "create_product": VendorOperation(
                "create_product", "Create Product", "POST", "/products", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a product from a WooCommerce product object.",
            ),
            "delete_product": VendorOperation(
                "delete_product", "Delete Product", "DELETE", "/products/{product_id}?force=true",
                ("product_id",),
            ),
            "get_product": VendorOperation(
                "get_product", "Get Product", "GET", "/products/{product_id}", ("product_id",),
            ),
            "list_products": VendorOperation(
                "list_products", "List Products", "GET", "/products",
                description="List products; pass filters and per_page as query parameters.",
            ),
            "update_product": VendorOperation(
                "update_product", "Update Product", "PUT", "/products/{product_id}",
                ("product_id",), description="Update a product from a WooCommerce product object.",
            ),
        },
    ),
    "wordpress": VendorSpec(
        key="wordpress",
        display_name="WordPress",
        description=(
            "WordPress posts, pages, and users through the REST API on a "
            "self-hosted site. Provide the site hostname without a URL scheme."
        ),
        category="productivity",
        base_url="https://{host}/wp-json/wp/v2",
        auth_kind="basic",
        basic_user_field="username",
        basic_password_field="password",
        credential_fields=("username", "password"),
        extra_required=("host",),
        operations={
            "create_post": VendorOperation(
                "create_post", "Create Post", "POST", "/posts", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a post from a WordPress post object.",
            ),
            "update_post": VendorOperation(
                "update_post", "Update Post", "POST", "/posts/{post_id}", ("post_id",),
                description="Update a post; WordPress accepts POST for updates.",
            ),
            "get_post": VendorOperation(
                "get_post", "Get Post", "GET", "/posts/{post_id}", ("post_id",),
                description="Get a post; pass context as a query parameter.",
            ),
            "list_posts": VendorOperation(
                "list_posts", "List Posts", "GET", "/posts",
                description="List posts; pass search, status, and pagination as query parameters.",
            ),
            "delete_post": VendorOperation(
                "delete_post", "Delete Post", "DELETE", "/posts/{post_id}", ("post_id",),
                description="Delete a post; pass force=true to bypass the trash.",
            ),
            "create_page": VendorOperation(
                "create_page", "Create Page", "POST", "/pages", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a page from a WordPress page object.",
            ),
            "update_page": VendorOperation(
                "update_page", "Update Page", "POST", "/pages/{page_id}", ("page_id",),
                description="Update a page; WordPress accepts POST for updates.",
            ),
            "get_page": VendorOperation(
                "get_page", "Get Page", "GET", "/pages/{page_id}", ("page_id",),
                description="Get a page; pass context as a query parameter.",
            ),
            "list_pages": VendorOperation(
                "list_pages", "List Pages", "GET", "/pages",
                description="List pages; pass search, status, and pagination as query parameters.",
            ),
            "delete_page": VendorOperation(
                "delete_page", "Delete Page", "DELETE", "/pages/{page_id}", ("page_id",),
                description="Delete a page; pass force=true to bypass the trash.",
            ),
            "create_user": VendorOperation(
                "create_user", "Create User", "POST", "/users", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a user with username, email, password, and name fields.",
            ),
            "update_user": VendorOperation(
                "update_user", "Update User", "POST", "/users/{user_id}", ("user_id",),
                description="Update a user; WordPress accepts POST for updates.",
            ),
            "get_user": VendorOperation(
                "get_user", "Get User", "GET", "/users/{user_id}", ("user_id",),
                description="Get a user; pass context as a query parameter.",
            ),
            "list_users": VendorOperation(
                "list_users", "List Users", "GET", "/users",
                description="List users; pass search, roles, and pagination as query parameters.",
            ),
            "delete_current_user": VendorOperation(
                "delete_current_user", "Delete Current User", "DELETE", "/users/me",
                description="Delete the authenticated user; pass force=true to reassign content.",
            ),
        },
    ),
    "yourls": VendorSpec(
        key="yourls",
        display_name="YOURLS",
        description=(
            "YOURLS link shortening and statistics on a self-hosted instance. "
            "Provide the instance hostname without a URL scheme."
        ),
        category="communication",
        base_url="https://{host}",
        auth_kind="query",
        query_param="signature",
        credential_fields=("signature",),
        extra_required=("host",),
        operations={
            "shorten": VendorOperation(
                "shorten", "Shorten URL", "GET",
                "/yourls-api.php?action=shorturl&format=json",
                ("url",),
                description=(
                    "Shorten a URL. Pass url plus optional keyword and title as query "
                    "parameters."
                ),
            ),
            "expand": VendorOperation(
                "expand", "Expand URL", "GET",
                "/yourls-api.php?action=expand&format=json",
                ("shorturl",),
                description="Expand a short URL. Pass shorturl as a query parameter.",
            ),
            "get_stats": VendorOperation(
                "get_stats", "Get URL Stats", "GET",
                "/yourls-api.php?action=url-stats&format=json",
                ("shorturl",),
                description="Get click statistics for a short URL; pass shorturl.",
            ),
        },
    ),
    "zulip": VendorSpec(
        key="zulip",
        display_name="Zulip",
        description=(
            "Zulip users, channels, subscriptions, and messages on a self-hosted "
            "organization. Provide the Zulip hostname without a URL scheme."
        ),
        category="communication",
        base_url="https://{host}/api/v1",
        auth_kind="basic",
        basic_user_field="email",
        basic_password_field="api_key",
        credential_fields=("email", "api_key"),
        extra_required=("host",),
        operations={
            "get_message": VendorOperation(
                "get_message", "Get Message", "GET", "/messages/{message_id}", ("message_id",),
                description="Get a message; pass apply_markdown as a query parameter.",
            ),
            "list_streams": VendorOperation(
                "list_streams", "List Channels", "GET", "/streams",
                description="List channels; pass include_public or include_subscribed.",
            ),
            "list_subscriptions": VendorOperation(
                "list_subscriptions", "List Subscriptions", "GET", "/users/me/subscriptions",
                description="List subscribed channels; pass include_subscribers.",
            ),
            "list_topics": VendorOperation(
                "list_topics", "List Topics", "GET", "/users/me/{stream_id}/topics",
                ("stream_id",), description="List topics in a channel.",
            ),
            "get_user": VendorOperation(
                "get_user", "Get User", "GET", "/users/{user_id}", ("user_id",),
                description="Get a user by ID or email address.",
            ),
            "list_users": VendorOperation(
                "list_users", "List Users", "GET", "/users",
                description="List users; pass client_gravatar and include_custom_profile_fields.",
            ),
        },
    ),
}


# Keys intentionally left out of build_batch22_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH22_KEYS: dict[str, str] = {
    "write_binary_file": (
        "The Write Binary File node is a hidden local-filesystem action that writes "
        "binary item data to a path on the n8n host. It has no vendor host, "
        "credential, or REST endpoint, so there is nothing for a "
        "VendorRESTConnector to call."
    ),
    "xml": (
        "The XML node is a local transform that converts between JSON and XML "
        "inside the n8n process. It has no vendor host, credential, or REST "
        "endpoint, so there is nothing for a VendorRESTConnector to call."
    ),
    "you_tube": (
        "The YouTube node authenticates exclusively with the youTubeOAuth2Api "
        "credential, which requires an OAuth2 authorization-code flow and "
        "automatic access-token refresh. VendorRESTConnector only supports static "
        "bearer, basic, header, and query credentials and has no token exchange or "
        "refresh support. Its video upload and channel-banner operations also send "
        "binary data through resumable uploads, so the node cannot be represented "
        "without an OAuth2 token manager."
    ),
}


def _build_definition(spec: VendorSpec) -> ConnectorDefinitionV1:
    operations = {
        key: ConnectorOperationV1(
            connector_key=spec.key,
            connector_version="1.0.0",
            operation_key=key,
            operation_version="1.0.0",
            display_name=op.display_name,
            description=op.description or f"{op.display_name} for {spec.display_name}.",
            input_schema={
                "type": "object",
                "properties": {
                    "params": {"type": "object"},
                    "body": {"type": "object"},
                },
                "required": list(op.requires),
            },
            output_schema={"type": "object"},
            credential_require=spec.key,
            retryable=op.retryable,
            idempotency=op.idempotency,
            node_types=[spec.key],
        )
        for key, op in spec.operations.items()
    }
    credential_properties: dict[str, Any] = {
        field: {"type": "string", "title": field.replace("_", " ").title()}
        for field in spec.credential_fields
    }
    return ConnectorDefinitionV1(
        connector_key=spec.key,
        display_name=spec.display_name,
        description=spec.description,
        category=spec.category,
        connector_version="1.0.0",
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=operations,
        triggers={},
        credential_types={
            spec.key: CredentialTypeV1(
                type_key=spec.key,
                display_name=f"{spec.display_name} Credentials",
                description=f"Credentials for {spec.display_name}.",
                secret_fields=list(spec.credential_fields),
                validation_schema={"type": "object", "properties": credential_properties},
                encryption_required=True,
            )
        },
        metadata={
            "implementation": "native",
            "batch": "catalog_conversion_22",
        },
    )


def build_batch22_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 22 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
