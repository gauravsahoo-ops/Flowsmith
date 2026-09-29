"""DocuSign eSignature connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
)

DOCUSIGN_CONNECTOR_KEY = "docusign"
DOCUSIGN_CONNECTOR_VERSION = "1.0.0"
DOCUSIGN_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=DOCUSIGN_CONNECTOR_KEY,
        connector_version=DOCUSIGN_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=DOCUSIGN_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="docusign",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["docusign"],
    )


def build_docusign_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=DOCUSIGN_CONNECTOR_KEY,
        display_name="DocuSign",
        description="Automate electronic signatures, send document envelopes, and track completion status with DocuSign eSignature.",
        category="productivity",
        connector_version=DOCUSIGN_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "create_envelope": _operation(
                "create_envelope", "Create Envelope", "Send an envelope with documents and recipients for signature.",
                {
                    "email_subject": {"type": "string", "title": "Email Subject"},
                    "recipients": {"type": "object", "title": "Recipients Spec"},
                    "documents": {"type": "array", "items": {"type": "object"}, "title": "Documents Array"},
                    "status": {"type": "string", "title": "Status (sent or created)", "default": "sent"},
                },
                ["email_subject"],
                retryable=False, idempotency="non_idempotent",
            ),
            "get_envelope": _operation(
                "get_envelope", "Get Envelope Status", "Retrieve signing status and recipient progress for an envelope.",
                {
                    "envelope_id": {"type": "string", "title": "Envelope ID"},
                },
                ["envelope_id"],
            ),
            "list_envelopes": _operation(
                "list_envelopes", "List Envelopes", "Query envelopes created or modified since a given date.",
                {
                    "from_date": {"type": "string", "title": "From Date (ISO-8601 or YYYY-MM-DD)"},
                    "count": {"type": "integer", "title": "Count", "default": 25},
                    "status": {"type": "string", "title": "Filter Status (completed, sent, delivered)"},
                },
                ["from_date"],
            ),
            "list_templates": _operation(
                "list_templates", "List Templates", "Enumerate reusable eSignature document templates.",
                {
                    "count": {"type": "integer", "title": "Max Results", "default": 50},
                },
                [],
            ),
        },
        triggers={
            "envelope_status_webhook": ConnectorTriggerV1(
                connector_key=DOCUSIGN_CONNECTOR_KEY,
                connector_version=DOCUSIGN_CONNECTOR_VERSION,
                trigger_key="envelope_status_webhook",
                trigger_version="1.0.0",
                trigger_type="webhook",
                configuration_schema={
                    "type": "object",
                    "properties": {
                        "events": {"type": "array", "items": {"type": "string"}, "title": "Envelope Event Types"},
                    },
                },
                credential_require="docusign",
                node_types=["docusign"],
            )
        },
        credential_types={
            "docusign": CredentialTypeV1(
                type_key="docusign",
                display_name="DocuSign API Credentials",
                description="DocuSign API Account ID, environment (demo/na4/etc.), and OAuth Access Token.",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "title": "API Account ID"},
                        "access_token": {"type": "string", "title": "Access Token"},
                        "environment": {"type": "string", "title": "Environment (demo, na2, na3, na4, eu)", "default": "demo"},
                    },
                    "required": ["account_id", "access_token"],
                },
                encryption_required=True,
            )
        },
    )
