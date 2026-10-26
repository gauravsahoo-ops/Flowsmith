"""Native REST connectors for catalog conversion batch 11.

Each connector uses a fixed vendor host, an explicit auth contract, and
operation paths taken from the corresponding n8n node implementation. Keys
whose n8n node is a local transform, a platform-internal action, or a protocol
the shared :class:`~app.connectors.vendor_rest.VendorRESTConnector` cannot
authenticate are listed in :data:`UNSUPPORTED_BATCH11_KEYS` with the specific
reason instead of being given invented endpoints.
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


BATCH11_KEYS = frozenset({
    "lingva_nex",
    "linked_in",
    "lone_scale",
    "magento2",
    "mandrill",
    "markdown",
    "matrix",
    "medium",
    "message_an_agent",
    "metabase",
})


VENDOR_SPECS: dict[str, VendorSpec] = {
    "lingva_nex": VendorSpec(
        key="lingva_nex",
        display_name="LingvaNex",
        description="LingvaNex language detection and translation.",
        category="ai",
        base_url="https://api-b2b.backenster.com/b1/api/v3",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "get_languages": VendorOperation(
                "get_languages", "Get Languages", "GET", "/getLanguages",
                description="List supported languages; pass platform as a query parameter.",
            ),
            "translate": VendorOperation(
                "translate", "Translate", "POST", "/translate", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Translate text. The body accepts data, to, platform, from, and "
                    "translateMode matching the vendor API."
                ),
            ),
        },
    ),
    "lone_scale": VendorSpec(
        key="lone_scale",
        display_name="LoneScale",
        description="LoneScale contact enrichment, sourcing, company search, and lists.",
        category="crm",
        base_url="https://public-api.lonescale.com",
        auth_kind="header",
        auth_header="X-API-KEY",
        credential_fields=("api_key",),
        operations={
            "list_lists": VendorOperation(
                "list_lists", "List Lists", "GET", "/lists",
                description="List lists; pass entity as a query parameter.",
            ),
            "create_list": VendorOperation(
                "create_list", "Create List", "POST", "/lists", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "add_list_item": VendorOperation(
                "add_list_item", "Add List Item", "POST", "/lists/{list_id}/item", ("list_id",),
                retryable=False, idempotency="non_idempotent",
                description="Add a contact or company to a list.",
            ),
            "enrich_contact": VendorOperation(
                "enrich_contact", "Enrich Contact", "POST", "/trigger/enrich/sync", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "source_contacts": VendorOperation(
                "source_contacts", "Source Contacts", "POST", "/trigger/contact-sourcing/sync", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "search_companies": VendorOperation(
                "search_companies", "Search Companies", "GET", "/companies/search",
                description="Search companies; pass domain, linkedin_id, slug, name, or enrich as query parameters.",
            ),
        },
    ),
    "magento2": VendorSpec(
        key="magento2",
        display_name="Magento 2",
        description=(
            "Magento 2 customers, orders, invoices, and products on a self-hosted "
            "store. Provide the store hostname without a URL scheme."
        ),
        category="ecommerce",
        base_url="https://{host}",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("host",),
        operations={
            "create_customer": VendorOperation(
                "create_customer", "Create Customer", "POST", "/rest/V1/customers", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a customer; the body must use Magento's customer wrapper.",
            ),
            "get_customer": VendorOperation(
                "get_customer", "Get Customer", "GET", "/rest/default/V1/customers/{customer_id}",
                ("customer_id",),
            ),
            "list_customers": VendorOperation(
                "list_customers", "List Customers", "GET", "/rest/default/V1/customers/search",
                description="Search customers; pass search_criteria as a query parameter.",
            ),
            "update_customer": VendorOperation(
                "update_customer", "Update Customer", "PUT", "/rest/V1/customers/{customer_id}",
                ("customer_id",), description="Update a customer; the body must use Magento's customer wrapper.",
            ),
            "delete_customer": VendorOperation(
                "delete_customer", "Delete Customer", "DELETE", "/rest/default/V1/customers/{customer_id}",
                ("customer_id",),
            ),
            "create_invoice": VendorOperation(
                "create_invoice", "Create Invoice", "POST", "/rest/default/V1/order/{order_id}/invoice",
                ("order_id",), retryable=False, idempotency="non_idempotent",
            ),
            "cancel_order": VendorOperation(
                "cancel_order", "Cancel Order", "POST", "/rest/default/V1/orders/{order_id}/cancel",
                ("order_id",), retryable=False, idempotency="non_idempotent",
            ),
            "get_order": VendorOperation(
                "get_order", "Get Order", "GET", "/rest/default/V1/orders/{order_id}", ("order_id",),
            ),
            "ship_order": VendorOperation(
                "ship_order", "Ship Order", "POST", "/rest/default/V1/order/{order_id}/ship",
                ("order_id",), retryable=False, idempotency="non_idempotent",
            ),
            "list_orders": VendorOperation(
                "list_orders", "List Orders", "GET", "/rest/default/V1/orders",
                description="Search orders; pass search_criteria as a query parameter.",
            ),
            "create_product": VendorOperation(
                "create_product", "Create Product", "POST", "/rest/default/V1/products", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a product; the body must use Magento's product wrapper.",
            ),
            "get_product": VendorOperation(
                "get_product", "Get Product", "GET", "/rest/default/V1/products/{sku}", ("sku",),
            ),
            "list_products": VendorOperation(
                "list_products", "List Products", "GET", "/rest/default/V1/products",
                description="Search products; pass search_criteria as a query parameter.",
            ),
            "update_product": VendorOperation(
                "update_product", "Update Product", "PUT", "/rest/default/V1/products/{sku}", ("sku",),
                description="Update a product; the body must use Magento's product wrapper.",
            ),
            "delete_product": VendorOperation(
                "delete_product", "Delete Product", "DELETE", "/rest/default/V1/products/{sku}", ("sku",),
            ),
        },
    ),
    "matrix": VendorSpec(
        key="matrix",
        display_name="Matrix",
        description=(
            "Matrix rooms, messages, events, and membership on a self-hosted "
            "homeserver. Provide the homeserver hostname without a URL scheme."
        ),
        category="communication",
        base_url="https://{host}/_matrix/client/r0",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("host",),
        operations={
            "whoami": VendorOperation("whoami", "Get Current Account", "GET", "/account/whoami"),
            "create_room": VendorOperation(
                "create_room", "Create Room", "POST", "/createRoom", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "join_room": VendorOperation(
                "join_room", "Join Room", "POST", "/rooms/{room_id}/join", ("room_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "leave_room": VendorOperation(
                "leave_room", "Leave Room", "POST", "/rooms/{room_id}/leave", ("room_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "invite_user": VendorOperation(
                "invite_user", "Invite User", "POST", "/rooms/{room_id}/invite", ("room_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "kick_user": VendorOperation(
                "kick_user", "Kick User", "POST", "/rooms/{room_id}/kick", ("room_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "send_message": VendorOperation(
                "send_message", "Send Message", "PUT",
                "/rooms/{room_id}/send/m.room.message/{transaction_id}",
                ("room_id", "transaction_id"),
                description=(
                    "Send a room message. The body accepts msgtype, body, format, and "
                    "formatted_body; transaction_id makes the send idempotent."
                ),
            ),
            "list_messages": VendorOperation(
                "list_messages", "List Messages", "GET", "/rooms/{room_id}/messages", ("room_id",),
                description="List room messages; pass dir, from, limit, or filter as query parameters.",
            ),
            "get_event": VendorOperation(
                "get_event", "Get Event", "GET", "/rooms/{room_id}/event/{event_id}",
                ("room_id", "event_id"),
            ),
            "list_members": VendorOperation(
                "list_members", "List Room Members", "GET", "/rooms/{room_id}/members", ("room_id",),
                description="List room members; pass membership or not_membership as query parameters.",
            ),
        },
    ),
    "medium": VendorSpec(
        key="medium",
        display_name="Medium",
        description="Medium posts and publications using a pre-issued access token.",
        category="communication",
        base_url="https://api.medium.com/v1",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "get_me": VendorOperation("get_me", "Get Current User", "GET", "/me"),
            "list_publications": VendorOperation(
                "list_publications", "List Publications", "GET", "/users/{user_id}/publications",
                ("user_id",),
            ),
            "create_post": VendorOperation(
                "create_post", "Create Post", "POST", "/users/{user_id}/posts", ("user_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create a post under a user with title, contentFormat, and content.",
            ),
            "create_publication_post": VendorOperation(
                "create_publication_post", "Create Publication Post", "POST",
                "/publications/{publication_id}/posts", ("publication_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create a post under a publication with title, contentFormat, and content.",
            ),
        },
    ),
}


# Keys intentionally left out of build_batch11_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH11_KEYS: dict[str, str] = {
    "linked_in": (
        "LinkedIn's n8n node authenticates through OAuth2 (linkedInOAuth2Api or "
        "linkedInCommunityManagementOAuth2Api) and every /rest call must carry "
        "LinkedIn-Version and X-Restli-Protocol-Version headers; media posts also "
        "upload binary data to an upload URL returned by the initializeUpload call. "
        "VendorRESTConnector cannot set vendor-specific request headers or handle "
        "binary uploads, so it cannot satisfy the LinkedIn REST protocol."
    ),
    "mandrill": (
        "Mandrill authenticates by adding the API key to the JSON request body "
        "(the 'key' field) of every call under /api/1.0. VendorRESTConnector only "
        "supports bearer, basic, header, and query credentials and never injects "
        "credentials into the body, so Mandrill requests would be unauthenticated."
    ),
    "markdown": (
        "The Markdown node is a local transform that converts between Markdown and "
        "HTML. It has no vendor host, credential, or REST endpoint, so there is "
        "nothing for a VendorRESTConnector to call."
    ),
    "message_an_agent": (
        "Message an Agent runs an agent inside the n8n instance through the platform "
        "executeAgent API. It has no vendor host, credential, or REST endpoint. "
        "VendorRESTConnector is a vendor HTTP connector and cannot invoke an "
        "instance-local agent."
    ),
    "metabase": (
        "Metabase's n8n credential exchanges a username and password for an "
        "expirable session token at POST /api/session, then sends that token in "
        "the X-Metabase-Session header. VendorRESTConnector has no pre-authentication "
        "or session-exchange support, and Metabase does not accept basic auth for "
        "its API, so every request would be unauthenticated."
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
            "batch": "catalog_conversion_11",
        },
    )


def build_batch11_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 11 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
