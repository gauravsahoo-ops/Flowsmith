"""Microsoft Dynamics 365 / Dataverse connector definition.

Exposes operations over Microsoft Dataverse Web API v9.2:
1. query           - OData query ($filter, $select, $expand, $orderby, $top) or FetchXML
2. search          - Search records matching field criteria
3. get             - Get single record by GUID
4. create          - Create new record (Contact, Account, Lead, Incident, custom table)
5. update          - Update record fields by GUID
6. upsert          - Upsert record using alternate key
7. delete          - Delete record by GUID
8. execute_action  - Trigger custom/unbound Dataverse action
"""

from __future__ import annotations

from typing import Any

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

DYNAMICS_CRM_CONNECTOR_KEY = "dynamics_crm"
DYNAMICS_CRM_CONNECTOR_VERSION = "1.0.0"
DYNAMICS_CRM_OPERATION_VERSION = "1.0.0"

_TIMEOUT_PROP = {
    "type": "number",
    "title": "Timeout (seconds)",
    "default": 30,
    "minimum": 1,
    "description": "Request timeout in seconds.",
}

STANDARD_OBJECTS = [
    "accounts",
    "contacts",
    "leads",
    "opportunities",
    "incidents",
    "tasks",
    "phonecalls",
    "emails",
    "systemusers",
]


def _operation(
    key: str,
    display_name: str,
    description: str,
    input_properties: dict[str, Any],
    required: list[str],
    output_schema: dict[str, Any],
    *,
    retryable: bool = False,
    idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=DYNAMICS_CRM_CONNECTOR_KEY,
        connector_version=DYNAMICS_CRM_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=DYNAMICS_CRM_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="dynamics_crm",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["dynamics_crm"],
    )


def _dynamics_operations() -> dict[str, ConnectorOperationV1]:
    entity_type_prop = {
        "type": "string",
        "title": "Entity / Table",
        "default": "contacts",
        "description": "Target entity set (e.g. 'contacts', 'accounts', 'leads', 'incidents' or custom schema name).",
    }

    return {
        "query": _operation(
            "query",
            "Query Records (OData / FetchXML)",
            "Query Dataverse records using standard OData query parameters ($filter, $select, $expand, $orderby, $top) or native FetchXML.",
            {
                "entity": entity_type_prop,
                "filter": {
                    "type": "string",
                    "title": "OData Filter ($filter)",
                    "description": "OData filter expression, e.g. statecode eq 0 and statuscode eq 1",
                },
                "select": {
                    "type": "string",
                    "title": "Fields ($select)",
                    "description": "Comma-separated list of attributes to return, e.g. firstname,lastname,emailaddress1",
                },
                "expand": {
                    "type": "string",
                    "title": "Expand ($expand)",
                    "description": "Navigation properties to expand, e.g. primarycontactid($select=fullname)",
                },
                "orderby": {
                    "type": "string",
                    "title": "Sort ($orderby)",
                    "description": "Order by expression, e.g. createdon desc",
                },
                "top": {
                    "type": "integer",
                    "title": "Limit ($top)",
                    "description": "Maximum number of records to return.",
                    "default": 50,
                },
                "fetchXml": {
                    "type": "string",
                    "title": "FetchXML",
                    "description": "Optional raw FetchXML query string. Overrides OData query parameters when provided.",
                },
                "timeout": _TIMEOUT_PROP,
            },
            ["entity"],
            {
                "type": "object",
                "properties": {
                    "records": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
        "search": _operation(
            "search",
            "Search Records",
            "Search records in a table matching field criteria.",
            {
                "entity": entity_type_prop,
                "filter": {
                    "type": "string",
                    "title": "Search Filter",
                    "description": "OData query expression or substring match.",
                },
                "select": {"type": "string", "title": "Fields to Return"},
                "top": {"type": "integer", "title": "Limit", "default": 10},
                "timeout": _TIMEOUT_PROP,
            },
            ["entity"],
            {
                "type": "object",
                "properties": {
                    "records": {"type": "array", "items": {"type": "object"}},
                    "count": {"type": "integer"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
        "get": _operation(
            "get",
            "Get Record by ID",
            "Retrieve a single record by its Dataverse GUID.",
            {
                "entity": entity_type_prop,
                "record_id": {
                    "type": "string",
                    "title": "Record ID (GUID)",
                    "description": "Primary key GUID of the record.",
                },
                "select": {"type": "string", "title": "Fields to Return ($select)"},
                "expand": {"type": "string", "title": "Expand ($expand)"},
                "timeout": _TIMEOUT_PROP,
            },
            ["entity", "record_id"],
            {"type": "object"},
            retryable=True,
            idempotency="idempotent",
        ),
        "create": _operation(
            "create",
            "Create Record",
            "Create a new row in a Dataverse table (Contact, Account, Lead, Case, or custom table).",
            {
                "entity": entity_type_prop,
                "data": {
                    "type": "object",
                    "title": "Record Data",
                    "description": "Key-value dictionary of column names and values to set.",
                },
                "timeout": _TIMEOUT_PROP,
            },
            ["entity", "data"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "title": "Created Record GUID"},
                    "entity_set": {"type": "string"},
                },
            },
            retryable=False,
            idempotency="non_idempotent",
        ),
        "update": _operation(
            "update",
            "Update Record",
            "Update fields on an existing record by GUID.",
            {
                "entity": entity_type_prop,
                "record_id": {
                    "type": "string",
                    "title": "Record ID (GUID)",
                    "description": "Primary key GUID of the record to update.",
                },
                "data": {
                    "type": "object",
                    "title": "Updated Data",
                    "description": "Key-value dictionary of column names and values to update.",
                },
                "timeout": _TIMEOUT_PROP,
            },
            ["entity", "record_id", "data"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "updated": {"type": "boolean"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
        "upsert": _operation(
            "upsert",
            "Upsert Record",
            "Insert or update a record using an alternate key.",
            {
                "entity": entity_type_prop,
                "key_field": {
                    "type": "string",
                    "title": "Alternate Key Field",
                    "description": "Name of the alternate key column.",
                },
                "key_value": {
                    "type": "string",
                    "title": "Alternate Key Value",
                    "description": "Value of the alternate key to match.",
                },
                "data": {
                    "type": "object",
                    "title": "Record Data",
                    "description": "Data to apply to the record.",
                },
                "timeout": _TIMEOUT_PROP,
            },
            ["entity", "key_field", "key_value", "data"],
            {
                "type": "object",
                "properties": {
                    "upserted": {"type": "boolean"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
        "delete": _operation(
            "delete",
            "Delete Record",
            "Delete a record by its GUID.",
            {
                "entity": entity_type_prop,
                "record_id": {
                    "type": "string",
                    "title": "Record ID (GUID)",
                    "description": "Primary key GUID of the record to delete.",
                },
                "timeout": _TIMEOUT_PROP,
            },
            ["entity", "record_id"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "deleted": {"type": "boolean"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
        "execute_action": _operation(
            "execute_action",
            "Execute Dataverse Action",
            "Call a custom or unbound Dataverse Web API action.",
            {
                "action_name": {
                    "type": "string",
                    "title": "Action Name",
                    "description": "Name of the unbound action, e.g. 'WhoAmI' or custom solution action.",
                },
                "payload": {
                    "type": "object",
                    "title": "Action Parameters",
                    "description": "JSON payload required by the action.",
                },
                "timeout": _TIMEOUT_PROP,
            },
            ["action_name"],
            {"type": "object"},
            retryable=False,
            idempotency="conditionally_idempotent",
        ),
    }


def _dynamics_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "dynamics_crm": CredentialTypeV1(
            type_key="dynamics_crm",
            display_name="Microsoft Dynamics 365 (Dataverse)",
            description=(
                "Microsoft Dynamics 365 CRM connection. Supports 1-Click OAuth2 authentication "
                "or Server-to-Server (Client Credentials) with Azure Entra ID."
            ),
            secret_fields=["client_secret", "refresh_token", "access_token"],
            validation_schema={
                "type": "object",
                "required": ["instance_url"],
                "properties": {
                    "instance_url": {"type": "string", "title": "Dynamics 365 Org URL (e.g. https://org.crm.dynamics.com)"},
                    "auth_type": {"type": "string", "title": "Auth Type", "enum": ["oauth2", "client_credentials"], "default": "oauth2"},
                    "tenant_id": {"type": "string", "title": "Azure AD Tenant ID", "default": "common"},
                    "client_id": {"type": "string", "title": "Application (client) ID"},
                    "client_secret": {"type": "string", "title": "Client Secret"},
                    "refresh_token": {"type": "string", "title": "OAuth2 Refresh Token"},
                    "oauth": {"type": "boolean", "title": "OAuth-connected", "default": False},
                },
            },
            encryption_required=True,
        )
    }


def build_dynamics_crm_definition() -> ConnectorDefinitionV1:
    """Build the Microsoft Dynamics 365 connector definition (v1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=DYNAMICS_CRM_CONNECTOR_KEY,
        display_name="Microsoft Dynamics 365",
        description="Microsoft Dynamics 365 CRM connector: query, create, update, upsert, and delete records across standard and custom Dataverse tables.",
        category="crm",
        connector_version=DYNAMICS_CRM_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_dynamics_operations(),
        triggers={},
        credential_types=_dynamics_credential_type(),
        metadata={
            "initial_operations": ["query", "get", "create", "update", "upsert", "delete", "execute_action"],
            "auth": "OAuth2 (Connect Microsoft Dynamics 365) or Azure App Registration Service Principal",
            "api_version": "v9.2",
        },
        icon="🔷",
    )
