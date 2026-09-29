"""SAP S/4HANA ERP connector definition (Phase 39)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

SAP_CONNECTOR_KEY = "sap"
SAP_CONNECTOR_VERSION = "1.0.0"
SAP_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=SAP_CONNECTOR_KEY,
        connector_version=SAP_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=SAP_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="sap",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["sap"],
    )


def build_sap_definition() -> ConnectorDefinitionV1:
    service_prop = {"type": "string", "title": "OData Service (e.g. API_BUSINESS_PARTNER, API_SALES_ORDER_SRV)", "default": "API_BUSINESS_PARTNER"}
    entity_set_prop = {"type": "string", "title": "Entity Set (e.g. A_BusinessPartner, A_SalesOrder)", "default": "A_BusinessPartner"}

    return ConnectorDefinitionV1(
        connector_key=SAP_CONNECTOR_KEY,
        display_name="SAP S/4HANA",
        description="Integrate with SAP S/4HANA Cloud & On-Premise via official OData v2/v4 services.",
        category="finance",
        connector_version=SAP_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "query_odata": _operation(
                "query_odata", "Query OData Entities", "Query SAP business entities using OData filters, pagination, and projection.",
                {
                    "service": service_prop,
                    "entity_set": entity_set_prop,
                    "filter": {"type": "string", "title": "OData $filter expression (e.g. Customer ne '' and Country eq 'US')"},
                    "select": {"type": "string", "title": "Comma-separated $select fields"},
                    "top": {"type": "integer", "title": "Max records ($top)", "default": 50},
                    "skip": {"type": "integer", "title": "Offset ($skip)", "default": 0},
                    "orderby": {"type": "string", "title": "Sort order ($orderby)"},
                    "expand": {"type": "string", "title": "Navigation property expansion ($expand)"},
                },
                ["service", "entity_set"],
            ),
            "get_entity": _operation(
                "get_entity", "Get Entity", "Fetch a single SAP business object by key (e.g. BusinessPartner='1000001').",
                {
                    "service": service_prop,
                    "entity_set": entity_set_prop,
                    "entity_key": {"type": "string", "title": "Entity key value (e.g. '1000042')"},
                    "select": {"type": "string", "title": "Comma-separated $select fields"},
                },
                ["service", "entity_set", "entity_key"],
            ),
            "create_entity": _operation(
                "create_entity", "Create Entity", "Create a new business record in SAP S/4HANA with CSRF token handshake.",
                {
                    "service": service_prop,
                    "entity_set": entity_set_prop,
                    "data": {"type": "object", "title": "Entity field attributes"},
                },
                ["service", "entity_set", "data"],
                retryable=False, idempotency="non_idempotent",
            ),
            "update_entity": _operation(
                "update_entity", "Update Entity", "Patch/update fields of an existing SAP entity record.",
                {
                    "service": service_prop,
                    "entity_set": entity_set_prop,
                    "entity_key": {"type": "string", "title": "Entity key value"},
                    "data": {"type": "object", "title": "Updated fields payload"},
                },
                ["service", "entity_set", "entity_key", "data"],
            ),
            "delete_entity": _operation(
                "delete_entity", "Delete Entity", "Remove an entity record by key.",
                {
                    "service": service_prop,
                    "entity_set": entity_set_prop,
                    "entity_key": {"type": "string", "title": "Entity key value"},
                },
                ["service", "entity_set", "entity_key"],
            ),
            "get_metadata": _operation(
                "get_metadata", "Get Service Metadata", "Introspect dynamic EDMX XML schema metadata for an SAP OData service.",
                {
                    "service": service_prop,
                },
                ["service"],
            ),
        },
        triggers={
            "business_event": ConnectorTriggerV1(
                connector_key=SAP_CONNECTOR_KEY,
                connector_version=SAP_CONNECTOR_VERSION,
                trigger_key="business_event",
                trigger_version="1.0.0",
                trigger_type="webhook",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "event_type": {"type": "string", "title": "SAP Event Type (e.g. sap.s4.beh.businesspartner.v1.BusinessPartner.Created.v1)"},
                        "secret_token": {"type": "string", "title": "HMAC secret verification token"},
                    },
                },
                credential_require="sap",
            )
        },
        credential_types={
            "sap": CredentialTypeV1(
                type_key="sap",
                display_name="SAP S/4HANA Credentials",
                description="SAP S/4HANA Cloud / On-Premise host, basic auth or OAuth token.",
                secret_fields=["password", "token", "client_secret", "api_key"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "base_url": {"type": "string", "title": "SAP Instance URL (e.g. https://my-s4hana.ondemand.com)"},
                        "username": {"type": "string", "title": "Technical User / Communication User"},
                        "password": {"type": "string", "title": "Password"},
                        "token": {"type": "string", "title": "OAuth2 Bearer Token"},
                        "api_key": {"type": "string", "title": "SAP Business Accelerator Hub APIKey"},
                    },
                    "required": ["base_url"],
                },
                encryption_required=True,
            )
        },
    )
