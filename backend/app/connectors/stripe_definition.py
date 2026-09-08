"""Stripe connector definition (Phase 11 business connectors).

Form-encoded REST v1 operations with automatic Idempotency-Key on
writes (derived from execution context, stable across engine retries):

1. create_customer      - add a customer
2. get_customer         - fetch one customer
3. list_customers       - cursor-paginated listing
4. create_payment_intent- charge setup with idempotency guarantee
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorLifecycle,
    CredentialTypeV1,
)

STRIPE_CONNECTOR_KEY = "stripe"
STRIPE_CONNECTOR_VERSION = "1.0.0"
STRIPE_OPERATION_VERSION = "1.0.0"


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
        connector_key=STRIPE_CONNECTOR_KEY,
        connector_version=STRIPE_CONNECTOR_VERSION,
        operation_key=key,
        operation_version=STRIPE_OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema={"type": "object", "properties": input_properties, "required": required},
        output_schema=output_schema,
        credential_require="stripe",
        retryable=retryable,
        idempotency=idempotency,
        node_types=["stripe"],
    )


def _stripe_operations() -> dict[str, ConnectorOperationV1]:
    return {
        "create_customer": _operation(
            "create_customer", "Create Customer",
            "Create a Stripe customer.",
            {
                "email": {"type": "string", "title": "Email"},
                "name": {"type": "string", "title": "Name"},
                "metadata": {"type": "object", "title": "Metadata"},
            },
            ["email"],
            {"type": "object", "properties": {"id": {"type": "string"}, "success": {"type": "boolean"}}},
            # Writes carry an execution-scoped Idempotency-Key, so engine
            # retries cannot double-create.
            retryable=True,
            idempotency="idempotent",
        ),
        "get_customer": _operation(
            "get_customer", "Get Customer",
            "Fetch one customer by id (cus_…).",
            {"customer_id": {"type": "string", "title": "Customer id"}},
            ["customer_id"],
            {"type": "object", "properties": {"id": {"type": "string"}, "email": {"type": "string"}}},
            retryable=True,
        ),
        "list_customers": _operation(
            "list_customers", "List Customers",
            "List customers, newest first (starting_after pagination).",
            {
                "limit": {"type": "integer", "title": "Page size", "default": 50, "minimum": 1, "maximum": 100},
                "max_pages": {"type": "integer", "title": "Max pages", "default": 3, "minimum": 1, "maximum": 10},
                "email_filter": {"type": "string", "title": "Filter by email"},
            },
            [],
            {"type": "object", "properties": {"customers": {"type": "array", "items": {"type": "object"}}}},
            retryable=True,
        ),
        "create_payment_intent": _operation(
            "create_payment_intent", "Create Payment Intent",
            "Create a PaymentIntent for an amount in cents (idempotency-keyed).",
            {
                "amount": {"type": "integer", "title": "Amount (cents)"},
                "currency": {"type": "string", "title": "Currency", "default": "usd"},
                "customer_id": {"type": "string", "title": "Customer id (optional)"},
                "description": {"type": "string", "title": "Description"},
            },
            ["amount"],
            {
                "type": "object",
                "properties": {
                    "intent_id": {"type": "string"},
                    "status": {"type": "string"},
                    "client_secret": {"type": "string"},
                },
            },
            retryable=True,
            idempotency="idempotent",
        ),
    }


def _stripe_credential_type() -> dict[str, CredentialTypeV1]:
    return {
        "stripe": CredentialTypeV1(
            type_key="stripe",
            display_name="Stripe",
            description=(
                "Stripe secret key (sk_… / rk_…) — use a restricted key with only "
                "the permissions your workflows need."
            ),
            secret_fields=["secret_key"],
            validation_schema={
                "type": "object",
                "properties": {
                    "secret_key": {"type": "string", "title": "Secret key"},
                    "account_name": {"type": "string", "title": "Account name (display)"},
                },
                "required": ["secret_key"],
            },
            encryption_required=True,
        )
    }


def build_stripe_definition() -> ConnectorDefinitionV1:
    """Build the Stripe connector definition (version 1.0.0)."""
    return ConnectorDefinitionV1(
        connector_key=STRIPE_CONNECTOR_KEY,
        display_name="Stripe",
        description="Manage Stripe customers and payment intents over REST v1.",
        category="api",
        connector_version=STRIPE_CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations=_stripe_operations(),
        triggers={},
        credential_types=_stripe_credential_type(),
        metadata={
            "initial_operations": ["create_customer", "get_customer", "list_customers", "create_payment_intent"],
            "auth": "secret key (Bearer)",
            "rate_limits": "429 + Retry-After honored",
            "retries": "writes carry execution-scoped Idempotency-Key",
        },
        icon="💳",
    )
