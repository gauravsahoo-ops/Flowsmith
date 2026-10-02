"""Salesforce connector definition (Phase 6 → Phase 9, curated Resource→Operation matrix).

Single source of truth for 13 resources × operations. Every exposed
resource/operation has a real backend handler; "execute" is never a
Salesforce operation (engine generic).

Operations:
1. search            - Search/Get Record (find by field value)
2. get               - Get Record by id
3. create            - Create Record (non-idempotent, never auto-retried)
4. update            - Update Record by id
5. upsert            - Upsert Record by external id (idempotent-safe)
6. delete            - Delete Record by id
7. query             - SOQL Query with nextRecordsUrl pagination (Get Many)
8. describe          - Field discovery (Get Summary)
9. list              - Object discovery (all sobjects)
10. bulk             - Bulk API 2.0 ingest
11. custom_api_call   - Generic REST (Custom API Call resource)
12. flow_invoke       - Invoke autolaunched Flow (Flow resource)

Resources (13) with valid operation subsets are defined in
RESOURCE_OPERATION_MATRIX. Frontend must derive its browser from this
matrix via /api/connectors/salesforce/resources — no hard-coded
operation lists.

Input/output schemas mirror SalesforceConnectorParams, so discovery is
truthful. Every operation requires 'salesforce' credential.
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

SALESFORCE_CONNECTOR_KEY = "salesforce"
SALESFORCE_CONNECTOR_VERSION = "1.2.0"
SALESFORCE_OPERATION_VERSION = "1.1.0"

# Single source: resource → valid backend operation ids (frontend derives from this).
# Curated labels (Add Note etc.) are UI aliases → backend ids (Add Note→create with object Note).
RESOURCE_OPERATION_MATRIX: dict[str, list[str]] = {
    "Account": ["create", "upsert", "delete", "get", "query", "describe", "update", "custom_api_call"],
    "Attachment": ["create", "delete", "get", "query", "describe"],
    "Case": ["create", "upsert", "delete", "get", "query", "describe", "update"],
    "Contact": ["create", "upsert", "delete", "get", "query", "describe", "update"],
    "CustomObject": ["create", "upsert", "delete", "get", "query", "describe", "update", "custom_api_call"],
    "Document": ["create", "delete", "get", "query", "describe"],
    "Flow": ["flow_invoke", "custom_api_call"],
    "Lead": ["create", "upsert", "delete", "get", "query", "describe", "update"],
    "Opportunity": ["create", "upsert", "delete", "get", "query", "describe", "update"],
    "Search": ["search", "query", "list"],
    "Task": ["create", "upsert", "delete", "get", "query", "describe", "update"],
    "User": ["get", "query", "describe"],
    "CustomApiCall": ["custom_api_call"],
}

# Curated display mapping for frontend (label → backend id)
CURATED_OPERATION_LABELS: dict[str, dict[str, str]] = {
    "add_note": {"label": "Add Note", "hint": "Add note to an account", "backend": "create"},
    "create": {"label": "Create", "hint": "Create an account", "backend": "create"},
    "upsert": {"label": "Create or Update", "hint": "Create a new account, or update the current one if it already exists (upsert)", "backend": "upsert"},
    "delete": {"label": "Delete", "hint": "Delete an account", "backend": "delete"},
    "get": {"label": "Get", "hint": "Get an account", "backend": "get"},
    "get_many": {"label": "Get Many", "hint": "Get many accounts", "backend": "query"},
    "describe": {"label": "Get Summary", "hint": "Returns an overview of account's metadata", "backend": "describe"},
    "update": {"label": "Update", "hint": "Update an account", "backend": "update"},
    "custom_api_call": {"label": "Custom API Call", "hint": "Make a custom API call", "backend": "custom_api_call"},
}

_TIMEOUT_PROP = {
    "type": "number",
    "title": "Timeout (seconds)",
    "default": 30,
    "minimum": 1,
    "description": "Request timeout in seconds.",
}

_MAX_PAGES_PROP = {
    "type": "integer",
    "title": "Max pages",
    "default": 10,
    "minimum": 1,
    "maximum": 100,
    "description": "Maximum nextRecordsUrl pages followed for query results.",
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
    """Build a versioned Salesforce operation definition."""
    return ConnectorOperationV1(
        connector_key=SALESFORCE_CONNECTOR_KEY,
        connector_version=SALESFORCE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=SALESFORCE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="salesforce",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["salesforce"],
    )


def _salesforce_operations() -> dict[str, ConnectorOperationV1]:
    object_name = {
        "type": "string",
        "title": "Object API name",
        "default": "Account",
        "description": (
            "Salesforce object API name, e.g. Account, Contact, Lead, "
            "Opportunity or a custom object like My_Object__c."
        ),
    }
    record_id = {
        "type": "string",
        "title": "Record Id",
        "description": "The 18-char (or 15-char) Salesforce record id.",
    }
    record = {
        "type": "object",
        "title": "Record fields",
        "description": "Field map for the record, e.g. {\"Name\": \"Acme\"}. Use the schema discovery API to enumerate valid fields.",
    }
    records = {
        "type": "array",
        "items": {"type": "object"},
        "title": "Records",
        "description": "Record batch for Bulk API 2.0 (max 10,000 per job).",
    }
    soql = {
        "type": "string",
        "title": "SOQL query",
        "default": "SELECT Id, Name, Type, LastModifiedDate FROM Account",
        "description": "SOQL query executed against the org. No LIMIT = unlimited (paginated via max_pages).",
    }
    search_field = {
        "type": "string",
        "title": "Search field",
        "default": "Email",
        "description": "Field to match on, e.g. Email for Lead.",
    }
    search_value = {
        "type": "string",
        "title": "Search value",
        "description": "Value to search for, e.g. {{ $json.email }}.",
    }
    external_id_field = {
        "type": "string",
        "title": "External Id field",
        "description": "API name of an external-id/unique custom field, e.g. Legacy_Id__c.",
    }
    external_id = {
        "type": "string",
        "title": "External Id value",
        "description": "Value of the external-id field identifying the record.",
    }
    bulk_operation = {
        "type": "string",
        "enum": ["insert", "update", "upsert", "delete"],
        "default": "insert",
        "title": "Bulk operation",
        "description": "Bulk job type (upsert requires external_id_field; delete requires an Id column per record).",
    }

    return {
        "search": _operation(
            "search",
            "Search/Get Record",
            "Find a record by field value (e.g. Lead by Email) and return the full record.",
            {
                "object_name": object_name,
                "search_field": search_field,
                "search_value": search_value,
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["object_name", "search_field", "search_value"],
            {
                "type": "object",
                "properties": {
                    "found": {"type": "boolean", "description": "Whether a matching record exists."},
                    "record": {"type": ["object", "null"], "description": "The matched record fields, including Id."},
                    "object_name": {"type": "string"},
                    "search_field": {"type": "string"},
                },
            },
            retryable=True,
        ),
        "get": _operation(
            "get",
            "Get Record",
            "Fetch a single Salesforce record by its id.",
            {"object_name": object_name, "record_id": record_id, "timeout_seconds": _TIMEOUT_PROP},
            ["object_name", "record_id"],
            {
                "type": "object",
                "properties": {
                    "record": {"type": "object", "description": "The fetched record fields, including Id."},
                },
            },
            retryable=True,
        ),
        "create": _operation(
            "create",
            "Create Record",
            "Create a Salesforce record and return its new id. Never auto-retried (a retry could duplicate the record).",
            {"object_name": object_name, "record": record, "timeout_seconds": _TIMEOUT_PROP},
            ["object_name", "record"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The created record id."},
                    "success": {"type": "boolean"},
                    "duplicate_alert": {"type": "boolean", "description": "A duplicate rule fired in alert mode."},
                    "matched_records": {"type": "array", "items": {"type": "string"}},
                },
            },
            idempotency="non_idempotent",
        ),
        "update": _operation(
            "update",
            "Update Record",
            "Update fields of an existing Salesforce record.",
            {
                "object_name": object_name,
                "record_id": record_id,
                "record": record,
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["object_name", "record_id", "record"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The updated record id."},
                    "success": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
        "upsert": _operation(
            "upsert",
            "Upsert Record",
            "Create or update a record identified by an external-id field; safe to retry (no duplicates on re-run).",
            {
                "object_name": object_name,
                "external_id_field": external_id_field,
                "external_id": external_id,
                "record": record,
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["object_name", "external_id_field", "external_id", "record"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The upserted record id."},
                    "created": {"type": "boolean", "description": "True when the record was created."},
                    "success": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
        "delete": _operation(
            "delete",
            "Delete Record",
            "Delete a Salesforce record by its id.",
            {"object_name": object_name, "record_id": record_id, "timeout_seconds": _TIMEOUT_PROP},
            ["object_name", "record_id"],
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The deleted record id."},
                    "success": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
        "query": _operation(
            "query",
            "SOQL Query",
            "Run a SOQL query against the org, following nextRecordsUrl pages up to max_pages. When done=false, feed nextRecordsUrl back via SOQL-free continuation or raise max_pages.",
            {"soql": soql, "max_pages": _MAX_PAGES_PROP, "timeout_seconds": _TIMEOUT_PROP},
            ["soql"],
            {
                "type": "object",
                "properties": {
                    "records": {"type": "array", "items": {"type": "object"}},
                    "totalSize": {"type": "integer"},
                    "done": {"type": "boolean"},
                    "nextRecordsUrl": {"type": ["string", "null"]},
                },
            },
            retryable=True,
        ),
        "describe": _operation(
            "describe",
            "Describe Object",
            "Field discovery: rich metadata for one object (field names, labels, types, picklist values, required flags, reference targets).",
            {"object_name": object_name, "timeout_seconds": _TIMEOUT_PROP},
            ["object_name"],
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "label": {"type": "string"},
                    "createable": {"type": "boolean"},
                    "updateable": {"type": "boolean"},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "label": {"type": "string"},
                                "type": {"type": "string"},
                                "createable": {"type": "boolean"},
                                "updateable": {"type": "boolean"},
                                "required": {"type": "boolean"},
                                "picklist_values": {"type": "array", "items": {"type": "string"}},
                                "reference_to": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
            retryable=True,
        ),
        "list": _operation(
            "list",
            "List Objects",
            "Object discovery: all sobjects in the org with their labels and create-ability.",
            {"timeout_seconds": _TIMEOUT_PROP},
            [],
            {
                "type": "object",
                "properties": {
                    "sobjects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "label": {"type": "string"},
                                "createable": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
            retryable=True,
        ),
        "bulk": _operation(
            "bulk",
            "Bulk Load (Bulk API 2.0)",
            "Load a batch of records through a Bulk API 2.0 ingest job (insert/update/upsert/delete). Insert jobs are never auto-retried.",
            {
                "object_name": object_name,
                "bulk_operation": bulk_operation,
                "records": records,
                "external_id_field": {**external_id_field, "title": "External Id field (upsert)"},
                "poll_interval_seconds": {
                    "type": "number", "title": "Poll interval (seconds)", "default": 1, "minimum": 0.1, "maximum": 30,
                },
                "max_polls": {"type": "integer", "title": "Max polls", "default": 60, "minimum": 1, "maximum": 600},
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["object_name", "bulk_operation", "records"],
            {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "state": {"type": "string", "description": "Terminal job state (JobComplete/JobFailed/Aborted)."},
                    "success": {"type": "boolean"},
                    "records_processed": {"type": "integer"},
                    "records_failed": {"type": "integer"},
                    "failed_records": {"type": "array", "items": {"type": "object"}},
                    "successful_records": {"type": "array", "items": {"type": "object"}},
                    "error_message": {"type": "string"},
                },
            },
            # One key spans four job types: insert must not be retried,
            # update/upsert/delete would be safe. Advertise conservatively;
            # the connector downgrades insert errors to non-retryable.
            retryable=False,
            idempotency="conditionally_idempotent",
        ),
        "custom_api_call": _operation(
            "custom_api_call",
            "Custom API Call",
            "Make a generic Salesforce REST API call (any path/method). Authenticated with the stored Salesforce credential.",
            {
                "custom_api_url": {"type": "string", "title": "API path", "description": "Salesforce REST path, e.g. /services/data/v63.0/sobjects/Account or /services/data/v63.0/actions/custom/flow/MyFlow", "default": "/services/data/v63.0/sobjects/Account"},
                "custom_api_method": {"type": "string", "title": "HTTP method", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "GET"},
                "custom_api_body": {"type": "object", "title": "Request body (for POST/PUT/PATCH)", "description": "JSON body for the custom call"},
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["custom_api_url"],
            {
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "object", "description": "Response JSON"},
                    "headers": {"type": "object"},
                },
            },
            retryable=True,
        ),
        "flow_invoke": _operation(
            "flow_invoke",
            "Invoke Flow",
            "Invoke an autolaunched Salesforce Flow via REST (Flow resource).",
            {
                "flow_api_name": {"type": "string", "title": "Flow API name", "description": "API name of the autolaunched flow, e.g. My_Flow"},
                "flow_inputs": {"type": "object", "title": "Flow inputs", "description": "Input variables for the flow"},
                "timeout_seconds": _TIMEOUT_PROP,
            },
            ["flow_api_name"],
            {
                "type": "object",
                "properties": {
                    "output": {"type": "object", "description": "Flow output"},
                    "success": {"type": "boolean"},
                },
            },
            retryable=True,
        ),
    }


def _salesforce_credential_type() -> dict[str, CredentialTypeV1]:
    """Credential type definition for the Salesforce OAuth2 credential.

    Mirrors the SalesforceCredential model (credentials/registry.py):
    the CredentialResolver validates against that model, and the fields
    below are exactly the non-secret shapes the API exposes.
    """
    return {
        "salesforce": CredentialTypeV1(
            type_key="salesforce",
            display_name="Salesforce",
            description=(
                "Salesforce org connection. Prefer 'Connect Salesforce' in the UI: the "
                "end user authorizes with their own account and the refresh token is "
                "stored encrypted. Manual entry (OAuth2 password or refresh-token grant) "
                "is supported for advanced setups."
            ),
            secret_fields=["client_secret", "password", "refresh_token"],
            validation_schema={
                "type": "object",
                "properties": {
                    "instance_url": {"type": "string", "title": "Org instance URL", "default": "https://login.salesforce.com"},
                    "login_url": {"type": "string", "title": "Authorization server URL (empty = instance_url)"},
                    "client_id": {"type": "string", "title": "Client Id (Consumer Key; server config for OAuth connections)"},
                    "client_secret": {"type": "string", "title": "Client Secret (Consumer Secret; server config for OAuth connections)"},
                    "username": {"type": "string", "title": "Username"},
                    "password": {"type": "string", "title": "Password"},
                    "refresh_token": {"type": "string", "title": "Refresh Token (alternative to username/password)"},
                    "oauth": {"type": "boolean", "title": "OAuth-connected (Connect Salesforce)", "default": False},
                    "api_version": {"type": "string", "title": "API version", "default": "v63.0"},
                },
            },
            encryption_required=True,
        )
    }


def _salesforce_triggers() -> dict[str, ConnectorTriggerV1]:
    """Event triggers (Phase 10): Salesforce Outbound Message receiver.

    trigger_type is "webhook" — the mechanism IS an inbound HTTP POST
    (SOAP) that the platform receives on a public URL, authenticated by
    the secret path suffix. CDC/Platform Events (CometD subscriber)
    are deliberately not offered: they need a persistent streaming
    connection this framework does not operate.
    """
    return {
        "outbound_message": ConnectorTriggerV1(
            connector_key=SALESFORCE_CONNECTOR_KEY,
            connector_version=SALESFORCE_CONNECTOR_VERSION,
            trigger_key="outbound_message",
            trigger_version="1.0.0",
            trigger_type="webhook",
            configuration_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "title": "Trigger path",
                        "pattern": r"^sf-outbound/[A-Za-z0-9_-]{6,64}$",
                        "description": "Secret URL suffix under /api/triggers/salesforce/, e.g. sf-outbound/lead-create-9f2ac1.",
                    },
                    "object_name": {
                        "type": "string",
                        "title": "Object filter (optional)",
                        "description": "Only execute for this object API name (e.g. Lead). Empty = all objects.",
                    },
                },
                "required": ["path"],
            },
            credential_require=None,
        ),
    }


def get_resource_operation_matrix() -> dict[str, list[str]]:
    """Expose resource→operation matrix for UI and validation (single source)."""
    return RESOURCE_OPERATION_MATRIX


def build_salesforce_definition() -> ConnectorDefinitionV1:
    """Build the Salesforce connector definition."""
    return ConnectorDefinitionV1(
        connector_key=SALESFORCE_CONNECTOR_KEY,
        display_name="Salesforce",
        description=(
            "Salesforce connector: CRUD plus upsert-by-external-id, SOQL queries with "
            "pagination, schema/field discovery, Bulk API 2.0 and generic REST/Flow invoke — one generic "
            "node covering standard and custom objects."
        ),
        category="crm",
        connector_version=SALESFORCE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_salesforce_operations(),
        triggers=_salesforce_triggers(),
        credential_types=_salesforce_credential_type(),
        metadata={
            "operations": [
                "search", "get", "create", "update", "upsert", "delete",
                "query", "describe", "list", "bulk", "custom_api_call", "flow_invoke",
            ],
            "resource_matrix": RESOURCE_OPERATION_MATRIX,
            "auth": "OAuth2 authorization-code (Connect Salesforce) or username-password grant",
            "discovery": "describe/list operations + live schema discovery API",
            "bulk_api": "REST Bulk API 2.0 ingest jobs (max 10,000 rows per job)",
            "event_triggers": (
                "Outbound Message receiver (SOAP webhook, at-least-once with "
                "MessageId deduplication). CDC/Platform Events unsupported: "
                "they need a persistent CometD subscriber."
            ),
        },
        icon="salesforce",
    )
