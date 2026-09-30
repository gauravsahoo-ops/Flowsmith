"""ServiceNow connector definition (Table API v1)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

SERVICENOW_CONNECTOR_KEY = "servicenow"
SERVICENOW_CONNECTOR_VERSION = "1.0.0"
SERVICENOW_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=SERVICENOW_CONNECTOR_KEY,
        connector_version=SERVICENOW_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=SERVICENOW_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="servicenow",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["servicenow"],
    )


def build_servicenow_definition() -> ConnectorDefinitionV1:
    table_prop = {"type": "string", "title": "Table (e.g. incident, change_request, sys_user)"}
    return ConnectorDefinitionV1(
        connector_key=SERVICENOW_CONNECTOR_KEY,
        display_name="ServiceNow",
        description="Manage ServiceNow ITSM records via the Table API (incident, change, problem, CMDB).",
        category="productivity",
        connector_version=SERVICENOW_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_records": _operation(
                "list_records", "List Records", "Query table rows with encoded query + limit/offset.",
                {
                    "table": table_prop,
                    "query": {"type": "string", "title": "Encoded query (e.g. active=true^priority=1)"},
                    "limit": {"type": "integer", "title": "Limit", "default": 25},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                    "fields": {"type": "string", "title": "Comma-separated fields (sysparm_fields)"},
                    "orderby": {"type": "string", "title": "Order by (sysparm_orderby)"},
                },
                ["table"],
            ),
            "get_record": _operation(
                "get_record", "Get Record", "Fetch one record by sys_id.",
                {"table": table_prop, "sys_id": {"type": "string", "title": "sys_id"}}, ["table", "sys_id"],
            ),
            "create_record": _operation(
                "create_record", "Create Record", "Insert a row into a table.",
                {"table": table_prop, "fields": {"type": "object", "title": "Field values"}},
                ["table", "fields"], retryable=False, idempotency="non_idempotent",
            ),
            "update_record": _operation(
                "update_record", "Update Record", "Patch fields of a record by sys_id.",
                {
                    "table": table_prop,
                    "sys_id": {"type": "string", "title": "sys_id"},
                    "fields": {"type": "object", "title": "Field values"},
                },
                ["table", "sys_id", "fields"],
            ),
            "delete_record": _operation(
                "delete_record", "Delete Record", "Delete a record by sys_id.",
                {"table": table_prop, "sys_id": {"type": "string", "title": "sys_id"}}, ["table", "sys_id"],
            ),
        },
        triggers={
            "record_updated": ConnectorTriggerV1(
                connector_key=SERVICENOW_CONNECTOR_KEY,
                connector_version=SERVICENOW_CONNECTOR_VERSION,
                trigger_key="record_updated",
                trigger_version="1.0.0",
                trigger_type="polling",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "table": {"type": "string", "title": "Table"},
                        "query": {"type": "string", "title": "Encoded query"},
                        "poll_interval_seconds": {"type": "integer", "default": 300},
                    },
                    "required": ["table"],
                },
                credential_require="servicenow",
                node_types=["servicenow"],
            ),
        },
        credential_types={
            "servicenow": CredentialTypeV1(
                type_key="servicenow",
                display_name="ServiceNow",
                description="ServiceNow instance + Basic auth or OAuth access token.",
                secret_fields=["password", "access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "instance": {"type": "string", "title": "Instance (acme or acme.service-now.com)"},
                        "username": {"type": "string", "title": "Username (Basic auth)"},
                        "password": {"type": "string", "title": "Password (Basic auth)"},
                        "access_token": {"type": "string", "title": "OAuth access token (alternative to Basic)"},
                    },
                    "required": ["instance"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["list_records", "get_record", "create_record", "update_record", "delete_record"], "auth": "Basic or OAuth2 Bearer (Table API)"},
        icon="🎫",
    )
