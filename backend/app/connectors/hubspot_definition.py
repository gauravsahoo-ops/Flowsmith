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

    return {
        "search": _operation(
            "search",
            "Search Record",
            "Find a record by property value (e.g. contact by email) and return it.",
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
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["object_type", "search_field", "search_value"],
            {
                "type": "object",
                "properties": {
                    "found": {"type": "boolean"},
                    "record": {"type": ["object", "null"], "description": "Matched record incl. id/properties."},
                    "object_type": {"type": "string"},
                    "search_field": {"type": "string"},
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
        description="HubSpot connector: search, get, create and update contacts, companies, deals and tickets via CRM v3.",
        category="api",
        connector_version=HUBSPOT_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_hubspot_operations(),
        triggers={},
        credential_types=_hubspot_credential_type(),
        metadata={
            "initial_operations": ["search", "get", "create", "update"],
            "auth": "OAuth2 authorization-code (Connect HubSpot) or private-app token",
        },
        icon="🧡",
    )
