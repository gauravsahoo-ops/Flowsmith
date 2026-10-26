"""Native REST connectors for catalog conversion batch 13.

Each implemented connector uses a fixed vendor host, an auth contract that
:class:`~app.connectors.vendor_rest.VendorRESTConnector` supports, and operation
paths taken from the matching n8n node implementation. Catalog keys whose n8n
node is a local transform, speaks a non-HTTP protocol, requires OAuth2 token
exchange, or needs a request encoding this connector family cannot produce are
listed in :data:`UNSUPPORTED_BATCH13_KEYS` with the specific reason. No
placeholder endpoints are invented for those keys.
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


BATCH13_CATALOG_KEYS = frozenset({
    "microsoft_teams",
    "microsoft_to_do",
    "mindee",
    "misp",
    "mistral_ai",
    "mocean",
    "monday_com",
    "mongo_db",
    "move_binary_data",
    "msg91",
})


VENDOR_SPECS: dict[str, VendorSpec] = {
    "misp": VendorSpec(
        key="misp",
        display_name="MISP",
        description=(
            "MISP threat-intelligence attributes, events, feeds, galaxies, "
            "organisations, tags, users, noticelists, and warninglists. Provide the "
            "MISP instance hostname without a URL scheme; the API key is sent raw "
            "in the Authorization header, as MISP expects."
        ),
        category="developer",
        base_url="https://{host}",
        auth_kind="header",
        auth_header="Authorization",
        credential_fields=("api_key",),
        extra_required=("host",),
        operations={
            "create_attribute": VendorOperation(
                "create_attribute", "Create Attribute", "POST",
                "/attributes/add/{event_id}", ("event_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Add an attribute to an event with type and value; extra MISP "
                    "fields go in the body."
                ),
            ),
            "delete_attribute": VendorOperation(
                "delete_attribute", "Delete Attribute", "DELETE",
                "/attributes/delete/{attribute_id}", ("attribute_id",),
            ),
            "get_attribute": VendorOperation(
                "get_attribute", "Get Attribute", "GET",
                "/attributes/view/{attribute_id}", ("attribute_id",),
            ),
            "list_attributes": VendorOperation(
                "list_attributes", "List Attributes", "GET", "/attributes",
                description="List attributes; pagination goes in payload.params.",
            ),
            "search_attributes": VendorOperation(
                "search_attributes", "Search Attributes", "POST", "/attributes/restSearch", (),
                retryable=False, idempotency="non_idempotent",
                description="Search attributes with MISP restSearch filters in the body.",
            ),
            "update_attribute": VendorOperation(
                "update_attribute", "Update Attribute", "PUT",
                "/attributes/edit/{attribute_id}", ("attribute_id",),
                description="Update attribute fields supplied in the body.",
            ),
            "create_event": VendorOperation(
                "create_event", "Create Event", "POST", "/events", (),
                retryable=False, idempotency="non_idempotent",
                description="Create an event with org_id, info, and optional fields.",
            ),
            "delete_event": VendorOperation(
                "delete_event", "Delete Event", "DELETE",
                "/events/delete/{event_id}", ("event_id",),
            ),
            "get_event": VendorOperation(
                "get_event", "Get Event", "GET", "/events/view/{event_id}", ("event_id",),
            ),
            "list_events": VendorOperation(
                "list_events", "List Events", "GET", "/events",
                description="List events; pagination goes in payload.params.",
            ),
            "search_events": VendorOperation(
                "search_events", "Search Events", "POST", "/events/restSearch", (),
                retryable=False, idempotency="non_idempotent",
                description="Search events with MISP restSearch filters in the body.",
            ),
            "publish_event": VendorOperation(
                "publish_event", "Publish Event", "POST",
                "/events/publish/{event_id}", ("event_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "unpublish_event": VendorOperation(
                "unpublish_event", "Unpublish Event", "POST",
                "/events/unpublish/{event_id}", ("event_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "update_event": VendorOperation(
                "update_event", "Update Event", "PUT",
                "/events/edit/{event_id}", ("event_id",),
                description="Update event fields supplied in the body.",
            ),
            "add_event_tag": VendorOperation(
                "add_event_tag", "Add Event Tag", "POST", "/events/addTag", (),
                retryable=False, idempotency="non_idempotent",
                description="Attach a tag to an event with event and tag in the body.",
            ),
            "remove_event_tag": VendorOperation(
                "remove_event_tag", "Remove Event Tag", "POST",
                "/events/removeTag/{event_id}/{tag_id}", ("event_id", "tag_id"),
                retryable=False, idempotency="non_idempotent",
            ),
            "create_feed": VendorOperation(
                "create_feed", "Create Feed", "POST", "/feeds/add", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a feed with name, provider, and url.",
            ),
            "disable_feed": VendorOperation(
                "disable_feed", "Disable Feed", "POST",
                "/feeds/disable/{feed_id}", ("feed_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "enable_feed": VendorOperation(
                "enable_feed", "Enable Feed", "POST",
                "/feeds/enable/{feed_id}", ("feed_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "get_feed": VendorOperation(
                "get_feed", "Get Feed", "GET", "/feeds/view/{feed_id}", ("feed_id",),
            ),
            "list_feeds": VendorOperation(
                "list_feeds", "List Feeds", "GET", "/feeds",
                description="List feeds; pagination goes in payload.params.",
            ),
            "update_feed": VendorOperation(
                "update_feed", "Update Feed", "PUT",
                "/feeds/edit/{feed_id}", ("feed_id",),
                description="Update feed fields supplied in the body.",
            ),
            "delete_galaxy": VendorOperation(
                "delete_galaxy", "Delete Galaxy", "DELETE",
                "/galaxies/delete/{galaxy_id}", ("galaxy_id",),
            ),
            "get_galaxy": VendorOperation(
                "get_galaxy", "Get Galaxy", "GET",
                "/galaxies/view/{galaxy_id}", ("galaxy_id",),
            ),
            "list_galaxies": VendorOperation(
                "list_galaxies", "List Galaxies", "GET", "/galaxies",
                description="List galaxies; pagination goes in payload.params.",
            ),
            "get_noticelist": VendorOperation(
                "get_noticelist", "Get Noticelist", "GET",
                "/noticelists/view/{noticelist_id}", ("noticelist_id",),
            ),
            "list_noticelists": VendorOperation(
                "list_noticelists", "List Noticelists", "GET", "/noticelists",
                description="List noticelists; pagination goes in payload.params.",
            ),
            "search_objects": VendorOperation(
                "search_objects", "Search Objects", "POST", "/objects/restSearch", (),
                retryable=False, idempotency="non_idempotent",
                description="Search MISP objects with restSearch filters in the body.",
            ),
            "create_organisation": VendorOperation(
                "create_organisation", "Create Organisation", "POST",
                "/admin/organisations/add", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_organisation": VendorOperation(
                "delete_organisation", "Delete Organisation", "DELETE",
                "/admin/organisations/delete/{organisation_id}", ("organisation_id",),
            ),
            "get_organisation": VendorOperation(
                "get_organisation", "Get Organisation", "GET",
                "/organisations/view/{organisation_id}", ("organisation_id",),
            ),
            "list_organisations": VendorOperation(
                "list_organisations", "List Organisations", "GET", "/organisations",
                description="List organisations; pagination goes in payload.params.",
            ),
            "update_organisation": VendorOperation(
                "update_organisation", "Update Organisation", "PUT",
                "/admin/organisations/edit/{organisation_id}", ("organisation_id",),
                description="Update organisation fields supplied in the body.",
            ),
            "create_tag": VendorOperation(
                "create_tag", "Create Tag", "POST", "/tags/add", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_tag": VendorOperation(
                "delete_tag", "Delete Tag", "POST",
                "/tags/delete/{tag_id}", ("tag_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_tags": VendorOperation(
                "list_tags", "List Tags", "GET", "/tags",
                description="List tags; pagination goes in payload.params.",
            ),
            "update_tag": VendorOperation(
                "update_tag", "Update Tag", "POST",
                "/tags/edit/{tag_id}", ("tag_id",),
                description="Update tag fields supplied in the body.",
            ),
            "create_user": VendorOperation(
                "create_user", "Create User", "POST", "/admin/users/add", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a user with email, role_id, and optional fields.",
            ),
            "delete_user": VendorOperation(
                "delete_user", "Delete User", "DELETE",
                "/admin/users/delete/{user_id}", ("user_id",),
            ),
            "get_user": VendorOperation(
                "get_user", "Get User", "GET", "/admin/users/view/{user_id}", ("user_id",),
            ),
            "list_users": VendorOperation(
                "list_users", "List Users", "GET", "/admin/users",
                description="List users; pagination goes in payload.params.",
            ),
            "update_user": VendorOperation(
                "update_user", "Update User", "PUT",
                "/admin/users/edit/{user_id}", ("user_id",),
                description="Update user fields supplied in the body.",
            ),
            "get_warninglist": VendorOperation(
                "get_warninglist", "Get Warninglist", "GET",
                "/warninglists/view/{warninglist_id}", ("warninglist_id",),
            ),
            "list_warninglists": VendorOperation(
                "list_warninglists", "List Warninglists", "GET", "/warninglists",
                description="List warninglists; pagination goes in payload.params.",
            ),
        },
    ),
    "mistral_ai": VendorSpec(
        key="mistral_ai",
        display_name="Mistral AI",
        description="Mistral AI document OCR and text extraction.",
        category="ai",
        base_url="https://api.mistral.ai",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "extract_text": VendorOperation(
                "extract_text", "Extract Text", "POST", "/v1/ocr", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Run OCR on a document. The body accepts model and a document "
                    "object with document_url or image_url; binary input can be "
                    "passed as a base64 data URL."
                ),
            ),
        },
    ),
    "msg91": VendorSpec(
        key="msg91",
        display_name="MSG91",
        description="MSG91 transactional SMS delivery.",
        category="communication",
        base_url="https://api.msg91.com/api",
        auth_kind="query",
        query_param="authkey",
        credential_fields=("authkey",),
        operations={
            "send_sms": VendorOperation(
                "send_sms", "Send SMS", "GET", "/sendhttp.php",
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send an SMS with sender, mobiles, and message query parameters; "
                    "the credential authkey is appended automatically."
                ),
            ),
        },
    ),
}


# Keys intentionally left out of build_batch13_connectors(). Keeping the reasons
# next to the implemented specs makes each gap explicit instead of publishing a
# connector whose operations cannot actually run.
UNSUPPORTED_BATCH13_KEYS: dict[str, str] = {
    "microsoft_teams": (
        "The n8n Microsoft Teams v2 node calls Microsoft Graph "
        "(https://graph.microsoft.com, or the graphApiBaseUrl supplied by the "
        "credential) under /v1.0/teams, /v1.0/chats, and /v1.0/users. It "
        "authenticates with the microsoftTeamsOAuth2Api OAuth2 credential or the "
        "microsoftEntraServicePrincipalApi client-credentials credential, so every "
        "request needs an access token that n8n mints and refreshes. "
        "VendorRESTConnector only supports a static API key or bearer token and has "
        "no OAuth2 token exchange, refresh, or credential-supplied Graph base URL."
    ),
    "microsoft_to_do": (
        "The n8n Microsoft To Do node calls Microsoft Graph at /v1.0/me/todo/lists "
        "(or /v1.0/users/{id}/todo/lists under service-principal auth) and "
        "authenticates with microsoftToDoOAuth2Api, microsoftOAuth2Api, or "
        "microsoftEntraServicePrincipalApi. Those credentials require an OAuth2 "
        "authorization-code/refresh flow or client-credentials token minting, and "
        "the Graph base URL is credential-supplied. VendorRESTConnector has neither "
        "an OAuth2 flow nor a static token that would remain valid."
    ),
    "mindee": (
        "The n8n Mindee node has a single predict operation per resource that "
        "uploads the input binary as multipart/form-data (a file or document "
        "field) to POST https://api.mindee.net/v1/products/mindee/"
        "expense_receipts/v4/predict or /invoices/v4/predict. VendorRESTConnector "
        "only sends JSON bodies and has no multipart or binary file-upload support, "
        "so it cannot execute the prediction request."
    ),
    "mocean": (
        "The n8n Mocean node authenticates by injecting the mocean-api-key and "
        "mocean-api-secret credential fields into a form-encoded POST body (together "
        "with mocean-resp-format=JSON) for /rest/2/sms and /rest/2/voice/dial. "
        "VendorRESTConnector only sends JSON bodies and never injects credentials "
        "into the body, so Mocean sends would be unauthenticated."
    ),
    "monday_com": (
        "Every n8n Monday.com operation is a GraphQL query or mutation POSTed to "
        "https://api.monday.com/v2 as {query, variables} with an API-Version header, "
        "and the operation is selected inside the GraphQL document rather than by a "
        "REST path. VendorRESTConnector has a fixed REST operation map and cannot "
        "set vendor headers or express GraphQL documents, so the boards, items, "
        "groups, columns, and updates operations cannot be represented without "
        "inventing REST endpoints."
    ),
    "mongo_db": (
        "The n8n MongoDB node talks to MongoDB over the mongodb:// or "
        "mongodb+srv:// wire protocol with the official mongodb driver (find, "
        "insert, update, aggregate, and related operations). It has no HTTP REST "
        "host or endpoint for VendorRESTConnector to call."
    ),
    "move_binary_data": (
        "The Convert to/from binary data (moveBinaryData) node is a hidden local "
        "transform that moves values between item JSON and binary properties with "
        "optional encoding conversion. It has no vendor host, credentials, or HTTP "
        "operations for VendorRESTConnector to call."
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
            "batch": "catalog_conversion_13",
        },
    )


def build_batch13_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 13 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
