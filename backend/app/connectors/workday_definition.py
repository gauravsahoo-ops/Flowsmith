"""Workday connector definition (Phase 39)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

WORKDAY_CONNECTOR_KEY = "workday"
WORKDAY_CONNECTOR_VERSION = "1.0.0"
WORKDAY_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=WORKDAY_CONNECTOR_KEY,
        connector_version=WORKDAY_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=WORKDAY_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="workday",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["workday"],
    )


def build_workday_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=WORKDAY_CONNECTOR_KEY,
        display_name="Workday",
        description="Integrate with Workday Enterprise HCM and Financial Management via WQL and REST APIs.",
        category="crm",
        connector_version=WORKDAY_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "query_wql": _operation(
                "query_wql", "Query WQL", "Execute a Workday Query Language (WQL) query to extract workers, payroll, or business objects.",
                {
                    "query": {"type": "string", "title": "WQL Query (e.g. SELECT worker, primaryWorkEmail, legalName FROM allWorkers)"},
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                },
                ["query"],
            ),
            "list_workers": _operation(
                "list_workers", "List Workers", "List and search employees and contingent workers.",
                {
                    "search": {"type": "string", "title": "Worker search term"},
                    "limit": {"type": "integer", "title": "Limit", "default": 50},
                    "offset": {"type": "integer", "title": "Offset", "default": 0},
                },
                [],
            ),
            "get_worker": _operation(
                "get_worker", "Get Worker", "Fetch full profile of a worker by Workday ID or Universal ID.",
                {"worker_id": {"type": "string", "title": "Worker ID"}},
                ["worker_id"],
            ),
            "update_worker": _operation(
                "update_worker", "Update Worker", "Update personal or contact details of a worker.",
                {
                    "worker_id": {"type": "string", "title": "Worker ID"},
                    "data": {"type": "object", "title": "Field update payload"},
                },
                ["worker_id", "data"],
            ),
            "get_organization": _operation(
                "get_organization", "Get Organization", "Retrieve details of a supervisory organization or cost center.",
                {"org_id": {"type": "string", "title": "Organization ID"}},
                ["org_id"],
            ),
            "create_requisition": _operation(
                "create_requisition", "Create Job Requisition", "Create a new recruiting job requisition.",
                {"data": {"type": "object", "title": "Requisition attributes"}},
                ["data"],
                retryable=False, idempotency="non_idempotent",
            ),
        },
        triggers={
            "outbound_event": ConnectorTriggerV1(
                connector_key=WORKDAY_CONNECTOR_KEY,
                connector_version=WORKDAY_CONNECTOR_VERSION,
                trigger_key="outbound_event",
                trigger_version="1.0.0",
                trigger_type="webhook",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "event_name": {"type": "string", "title": "Workday Event Name (e.g. Hire_Employee, Terminate_Employee)"},
                        "verification_secret": {"type": "string", "title": "Verification Secret"},
                    },
                },
                credential_require="workday",
            )
        },
        credential_types={
            "workday": CredentialTypeV1(
                type_key="workday",
                display_name="Workday Credentials",
                description="Workday API endpoint host, tenant name, and OAuth2 access token.",
                secret_fields=["token", "client_secret", "refresh_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "host": {"type": "string", "title": "Workday Host (e.g. https://wd2-impl-services1.workday.com)"},
                        "tenant": {"type": "string", "title": "Tenant Name"},
                        "token": {"type": "string", "title": "OAuth2 Bearer Token"},
                        "client_id": {"type": "string", "title": "Client ID (optional)"},
                        "client_secret": {"type": "string", "title": "Client Secret (optional)"},
                    },
                    "required": ["host", "tenant"],
                },
                encryption_required=True,
            )
        },
    )
