"""QuickBooks connector definition."""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)

QUICKBOOKS_CONNECTOR_KEY = "quickbooks"
QUICKBOOKS_CONNECTOR_VERSION = "1.0.0"
QUICKBOOKS_OPERATION_VERSION = "1.0.0"


def _operation(
    key: str, display_name: str, description: str,
    input_properties: dict, required: list[str], *,
    retryable: bool = True, idempotency: str = "idempotent",
) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=QUICKBOOKS_CONNECTOR_KEY,
        connector_version=QUICKBOOKS_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=QUICKBOOKS_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema={"type": "object", "properties": {}},
        credential_require="quickbooks",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["quickbooks"],
    )


def build_quickbooks_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=QUICKBOOKS_CONNECTOR_KEY,
        display_name="QuickBooks",
        description="QuickBooks Online company, customers, invoices, and queries.",
        category="finance",
        connector_version=QUICKBOOKS_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            "query": _operation(
                "query", "Query", "Run a QuickBooks query (select * from Customer ...).",
                {"query": {"type": "string", "title": "Query string"}}, ["query"],
            ),
            "get_company": _operation(
                "get_company", "Get Company", "Fetch company info.",
                {}, [],
            ),
            "create_customer": _operation(
                "create_customer", "Create Customer", "Create a customer.",
                {
                    "display_name": {"type": "string", "title": "Display name"},
                    "email": {"type": "string", "title": "Email"},
                },
                ["display_name"], retryable=False, idempotency="non_idempotent",
            ),
            "get_customer": _operation(
                "get_customer", "Get Customer", "Fetch one customer by id.",
                {"customer_id": {"type": "string", "title": "Customer id"}}, ["customer_id"],
            ),
            "create_invoice": _operation(
                "create_invoice", "Create Invoice", "Create an invoice for a customer.",
                {
                    "customer_ref": {"type": "string", "title": "Customer id"},
                    "lines": {"type": "string", "title": "Lines JSON array"},
                },
                ["customer_ref", "lines"], retryable=False, idempotency="non_idempotent",
            ),
            "get_invoice": _operation(
                "get_invoice", "Get Invoice", "Fetch one invoice by id.",
                {"invoice_id": {"type": "string", "title": "Invoice id"}}, ["invoice_id"],
            ),
        },
        triggers={},
        credential_types={
            "quickbooks": CredentialTypeV1(
                type_key="quickbooks",
                display_name="QuickBooks",
                description="QuickBooks Online OAuth token + company realm.",
                secret_fields=["access_token", "refresh_token"],
                validation_schema={
                    "type": "object",
                    "properties": {
                        "access_token": {"type": "string", "title": "Access token"},
                        "refresh_token": {"type": "string", "title": "Refresh token (optional)"},
                        "realm_id": {"type": "string", "title": "Company realm ID"},
                        "environment": {"type": "string", "title": "sandbox or production"},
                    },
                    "required": ["access_token", "realm_id"],
                },
                encryption_required=True,
            )
        },
        metadata={"initial_operations": ["query", "get_company", "create_customer", "get_customer", "create_invoice", "get_invoice"], "auth": "OAuth2 Bearer"},
        icon="🧾",
    )
