"""Oracle NetSuite ERP connector definition (Phase 39)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

NETSUITE_CONNECTOR_KEY = "netsuite"
NETSUITE_CONNECTOR_VERSION = "1.0.0"
NETSUITE_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=NETSUITE_CONNECTOR_KEY,
        connector_version=NETSUITE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=NETSUITE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="netsuite",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["netsuite"],
    )


def build_netsuite_definition() -> ConnectorDefinitionV1:
    rtype_prop = {"type": "string", "title": "Record Type (e.g. customer, salesOrder, invoice, vendor, item)", "default": "customer"}
    return ConnectorDefinitionV1(
        connector_key=NETSUITE_CONNECTOR_KEY,
        display_name="Oracle NetSuite ERP",
        description="Integrate with Oracle NetSuite ERP via SuiteTalk REST Web Services and SuiteQL.",
        category="finance",
        connector_version=NETSUITE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "query_suiteql": _operation(
                "query_suiteql", "Query SuiteQL", "Execute a SuiteQL SQL statement to query NetSuite financial and transaction tables.",
                {
                    "query": {"type": "string", "title": "SuiteQL Query (e.g. SELECT id, entityid, email FROM customer WHERE isinactive = 'F')"},
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                },
                ["query"],
            ),
            "list_records": _operation(
                "list_records", "List Records", "List records of a given type with optional filtering query ($q).",
                {
                    "record_type": rtype_prop,
                    "q": {"type": "string", "title": "Filter expression (e.g. email IS NOT NULL)"},
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                },
                ["record_type"],
            ),
            "get_record": _operation(
                "get_record", "Get Record", "Retrieve a single NetSuite record by ID.",
                {
                    "record_type": rtype_prop,
                    "record_id": {"type": "string", "title": "Internal record ID"},
                },
                ["record_type", "record_id"],
            ),
            "create_record": _operation(
                "create_record", "Create Record", "Insert a new record (customer, salesOrder, invoice, etc.).",
                {
                    "record_type": rtype_prop,
                    "data": {"type": "object", "title": "Record attributes"},
                },
                ["record_type", "data"],
                retryable=False, idempotency="non_idempotent",
            ),
            "update_record": _operation(
                "update_record", "Update Record", "Patch/update fields of an existing NetSuite record.",
                {
                    "record_type": rtype_prop,
                    "record_id": {"type": "string", "title": "Internal record ID"},
                    "data": {"type": "object", "title": "Fields payload"},
                },
                ["record_type", "record_id", "data"],
            ),
            "delete_record": _operation(
                "delete_record", "Delete Record", "Delete a NetSuite record by ID.",
                {
                    "record_type": rtype_prop,
                    "record_id": {"type": "string", "title": "Internal record ID"},
                },
                ["record_type", "record_id"],
            ),
            "get_metadata": _operation(
                "get_metadata", "Get Record Metadata", "Introspect dynamic schema and fields catalog for a NetSuite record type.",
                {
                    "record_type": rtype_prop,
                },
                ["record_type"],
            ),
        },
        triggers={
            "webhook": ConnectorTriggerV1(
                connector_key=NETSUITE_CONNECTOR_KEY,
                connector_version=NETSUITE_CONNECTOR_VERSION,
                trigger_key="webhook",
                trigger_version="1.0.0",
                trigger_type="webhook",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "record_type": {"type": "string", "title": "Record Type to monitor"},
                        "event": {"type": "string", "title": "Event (create, edit, delete)"},
                    },
                },
                credential_require="netsuite",
            )
        },
        credential_types={
            "netsuite": CredentialTypeV1(
                type_key="netsuite",
                display_name="Oracle NetSuite Credentials",
                description="NetSuite Account ID with Token-Based Authentication (TBA) or OAuth 2.0 token.",
                secret_fields=["token", "consumer_secret", "token_secret"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "title": "NetSuite Account ID (e.g. 1234567 or TSTDRV1234567)"},
                        "token": {"type": "string", "title": "OAuth 2.0 Bearer Token (optional if using TBA)"},
                        "consumer_key": {"type": "string", "title": "TBA Consumer Key"},
                        "consumer_secret": {"type": "string", "title": "TBA Consumer Secret"},
                        "token_id": {"type": "string", "title": "TBA Token ID"},
                        "token_secret": {"type": "string", "title": "TBA Token Secret"},
                    },
                    "required": ["account_id"],
                },
                encryption_required=True,
            )
        },
    )
