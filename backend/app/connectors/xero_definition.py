"""Xero accounting connector definition (Phase 40)."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

XERO_CONNECTOR_KEY = "xero"
XERO_CONNECTOR_VERSION = "1.0.0"
XERO_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=XERO_CONNECTOR_KEY,
        connector_version=XERO_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=XERO_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="xero",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["xero"],
    )


def build_xero_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=XERO_CONNECTOR_KEY,
        display_name="Xero",
        description="Automate bookkeeping, manage invoices, contacts, and chart of accounts with Xero Accounting.",
        category="finance",
        connector_version=XERO_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={
            "list_invoices": _operation(
                "list_invoices", "List Invoices", "Query accounts receivable/payable invoices.",
                {
                    "where": {"type": "string", "title": "Filter Expression (e.g. Status==\"PAID\")"},
                    "page": {"type": "integer", "title": "Page", "default": 1},
                },
                [],
            ),
            "get_invoice": _operation(
                "get_invoice", "Get Invoice", "Retrieve invoice details and line items by ID.",
                {
                    "invoice_id": {"type": "string", "title": "Invoice ID / GUID"},
                },
                ["invoice_id"],
            ),
            "create_invoice": _operation(
                "create_invoice", "Create Invoice", "Create a sales or purchase invoice in Xero.",
                {
                    "contact_id": {"type": "string", "title": "Contact ID"},
                    "line_items": {"type": "array", "items": {"type": "object"}, "title": "Line Items Array"},
                    "type_str": {"type": "string", "title": "Type (ACCREC or ACCPAY)", "default": "ACCREC"},
                    "due_date": {"type": "string", "title": "Due Date (YYYY-MM-DD)"},
                },
                ["contact_id", "line_items"],
                retryable=False, idempotency="non_idempotent",
            ),
            "list_contacts": _operation(
                "list_contacts", "List Contacts", "Enumerate customer and vendor contacts.",
                {
                    "page": {"type": "integer", "title": "Page", "default": 1},
                },
                [],
            ),
            "get_accounts": _operation(
                "get_accounts", "Get Accounts", "Retrieve the chart of accounts for the tenant.",
                {},
                [],
            ),
        },
        triggers={},
        credential_types={
            "xero": CredentialTypeV1(
                type_key="xero",
                display_name="Xero OAuth Credentials",
                description="Xero Tenant ID and OAuth 2.0 Access Token.",
                secret_fields=["access_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "tenant_id": {"type": "string", "title": "Xero Tenant ID (GUID)"},
                        "access_token": {"type": "string", "title": "OAuth 2.0 Access Token"},
                    },
                    "required": ["tenant_id", "access_token"],
                },
                encryption_required=True,
            )
        },
    )
