"""HubSpot connector definition (Phase 33).

Versioned ConnectorDefinitionV1 for the HubSpot connector, registered
through the ConnectorRegistry. The v3 CRM API is uniform across standard
objects, so one operation set covers contacts/companies/deals/tickets:

1. search - Search Record (find by property value)
2. get    - Get Record (by id)
3. create - Create Record
4. update - Update Record

Every operation requires the 'hubspot' credential type, which the
CredentialResolver supplies at run time.
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

HUBSPOT_CONNECTOR_KEY = "hubspot"
HUBSPOT_CONNECTOR_VERSION = "1.0.0"
HUBSPOT_OPERATION_VERSION = "1.0.0"

_TIMEOUT_PROP = {
    "type": "number",
    "title": "Timeout (seconds)",
    "default": 30,
    "minimum": 1,
    "description": "Request timeout in seconds.",
}


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
        connector_key=HUBSPOT_CONNECTOR_KEY,
        connector_version=HUBSPOT_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=HUBSPOT_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="hubspot",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["hubspot"],
    )


def _hubspot_operations() -> dict[str, ConnectorOperationV1]:
    object_type = {
        "type": "string",
        "title": "Object type",
        "default": "contacts",
        "enum": ["contacts", "companies", "deals", "tickets", "products", "quotes"],
        "description": "Standard CRM object the operation targets.",
    }
    record_id = {
        "type": "string",
        "title": "Record id",
        "description": "The HubSpot record id.",
    }
    properties = {
        "type": "object",
        "title": "Properties",
        "description": 'Property map for the record, e.g. {"email": "a@b.com"}.',
    }
    pagination_props = {
        "limit": {
            "type": "integer",
            "title": "Page size",
            "default": 100,
            "minimum": 1,
            "maximum": 250,
            "description": "How many records to fetch per request.",
        },
        "after": {
            "type": "string",
            "title": "Page cursor",
            "placeholder": "{{ $json.next_cursor }}",
            "description": "Cursor returned by the previous page. Leave empty to start at the beginning.",
        },
        "return_all": {
            "type": "boolean",
            "title": "Fetch all pages",
            "default": False,
            "description": "Follow cursors until the whole result set is retrieved.",
        },
        "max_pages": {
            "type": "integer",
            "title": "Max pages",
            "default": 10,
            "minimum": 1,
            "maximum": 100,
            "description": "Safety cap on how many pages a single run may fetch.",
        },
    }

    return {
        "search": _operation(
            "search",
            "Search Record",
            "Find records by property value (e.g. contacts by email), with cursor pagination.",
            {
                "object_type": object_type,
                "search_field": {
                    "type": "string",
                    "title": "Search property",
                    "default": "email",
                    "description": "Property to match on, e.g. email.",
                },
                "search_value": {
                    "type": "string",
                    "title": "Search value",
                    "description": "Value to search for, e.g. {{ $json.email }}.",
                },
                "limit": pagination_props["limit"],
                "after": pagination_props["after"],
                "return_all": pagination_props["return_all"],
                "max_pages": pagination_props["max_pages"],
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["object_type", "search_field", "search_value"],
            {
                "type": "object",
                "properties": {
                    "found": {"type": "boolean"},
                    "record": {"type": ["object", "null"], "description": "First matched record incl. id/properties."},
                    "records": {"type": "array", "description": "Every record fetched in this run."},
                    "object_type": {"type": "string"},
                    "search_field": {"type": "string"},
                    "total": {"type": "integer"},
                    "pages_fetched": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                    "next_offset": {"type": ["string", "null"], "description": "Cursor to pass to the next page."},
                },
            },
            retryable=True,
        ),
        "list": _operation(
            "list",
            "List Records",
            "Page through every record of an object using the v3 cursor contract.",
            {
                "object_type": object_type,
                "property_names": {
                    "type": "array",
                    "title": "Properties to return",
                    "items": {"type": "string"},
                    "description": "Leave empty for the object's default properties.",
                },
                "include_archived": {
                    "type": "boolean",
                    "title": "Include archived",
                    "default": False,
                    "description": "Also return archived records.",
                },
                "limit": pagination_props["limit"],
                "after": pagination_props["after"],
                "return_all": pagination_props["return_all"],
                "max_pages": pagination_props["max_pages"],
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["object_type"],
            {
                "type": "object",
                "properties": {
                    "object_type": {"type": "string"},
                    "records": {"type": "array"},
                    "count": {"type": "integer"},
                    "pages_fetched": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                    "next_cursor": {"type": ["string", "null"], "description": "Cursor for the next page."},
                },
            },
            retryable=True,
        ),
        "get": _operation(
            "get",
            "Get Record",
            "Fetch a single HubSpot record by its id.",
            {"object_type": object_type, "record_id": record_id, "timeout_seconds": _TIMEOUT_PROP},
            ["object_type", "record_id"],
            {"type": "object", "properties": {"record": {"type": "object"}}},
            retryable=True,
        ),
        "create": _operation(
            "create",
            "Create Record",
            "Create a HubSpot record and return its new id.",
            {"object_type": object_type, "properties": properties, "timeout_seconds": _TIMEOUT_PROP},
            ["object_type", "properties"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "success": {"type": "boolean"},
                },
            },
            idempotency="non_idempotent",
        ),
        "update": _operation(
            "update",
            "Update Record",
            "Update properties of an existing HubSpot record.",
            {
                "object_type": object_type,
                "record_id": record_id,
                "properties": properties,
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["object_type", "record_id", "properties"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "success": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
        "delete": _operation(
            "delete",
            "Delete Record",
            "Delete a HubSpot record by its id. Reports the result from the actual HTTP status.",
            {"object_type": object_type, "record_id": record_id, "timeout_seconds": _TIMEOUT_PROP},
            ["object_type", "record_id"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "object_type": {"type": "string"},
                    "deleted": {"type": "boolean"},
                    "http_status": {"type": "integer"},
                },
            },
            retryable=False,
            idempotency="idempotent",
        ),
        "get_properties": _operation(
            "get_properties",
            "Get Object Properties",
            "Retrieve metadata and schema for all properties defined on a HubSpot object type.",
            {"object_type": object_type, "timeout_seconds": _TIMEOUT_PROP},
            ["object_type"],
            {
                "type": "object",
                "properties": {
                    "object_type": {"type": "string"},
                    "properties": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                    "success": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
        "associate_records": _operation(
            "associate_records",
            "Associate Records",
            "Create an association link between two HubSpot CRM records.",
            {
                "from_object_type": {"type": "string", "title": "From object type", "default": "contacts"},
                "from_record_id": {"type": "string", "title": "From record ID"},
                "to_object_type": {"type": "string", "title": "To object type", "default": "companies"},
                "to_record_id": {"type": "string", "title": "To record ID"},
                "association_type_id": {"type": "string", "title": "Association type ID", "default": "1"},
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["from_object_type", "from_record_id", "to_object_type", "to_record_id"],
            {
                "type": "object",
                "properties": {
                    "from_object_type": {"type": "string"},
                    "from_record_id": {"type": "string"},
                    "to_object_type": {"type": "string"},
                    "to_record_id": {"type": "string"},
                    "association_type_id": {"type": "string"},
                    "success": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
    }


def _hubspot_credential_type() -> dict[str, CredentialTypeV1]:
    """Credential type definition mirroring HubSpotCredential."""
    return {
        "hubspot": CredentialTypeV1(
            type_key="hubspot",
            display_name="HubSpot",
            description=(
                "HubSpot CRM connection. Prefer 'Connect HubSpot' in the UI: the end user "
                "authorizes with their own account and the refresh token is stored encrypted. "
                "A private-app token is supported for simple setups."
            ),
            secret_fields=["refresh_token", "private_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "hub_id": {"type": "string", "title": "Portal id (display)"},
                    "user": {"type": "string", "title": "Authorizing user (display)"},
                    "refresh_token": {"type": "string", "title": "Refresh Token ('Connect HubSpot')"},
                    "private_token": {"type": "string", "title": "Private-app token"},
                    "oauth": {"type": "boolean", "title": "OAuth-connected", "default": False},
                },
            },
            encryption_required=True,
        )
    }


def build_hubspot_definition() -> ConnectorDefinitionV1:
    """Build the HubSpot connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=HUBSPOT_CONNECTOR_KEY,
        display_name="HubSpot",
        description="HubSpot connector: search, list, get, create, update and delete contacts, companies, deals and tickets via CRM v3, with cursor pagination.",
        category="crm",
        connector_version=HUBSPOT_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_hubspot_operations(),
        triggers={},
        credential_types=_hubspot_credential_type(),
        metadata={
            "initial_operations": ["search", "list", "get", "create", "update", "delete", "get_properties", "associate_records"],
            "pagination": {"strategy": "cursor", "params": ["limit", "after", "return_all", "max_pages"]},
            "auth": "OAuth2 authorization-code (Connect HubSpot) or private-app token",
        },
        icon="hubspot",
    )

