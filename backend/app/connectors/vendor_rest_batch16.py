"""Native REST connectors for catalog conversion batch 16.

Each implemented connector uses a fixed vendor host, an explicit auth contract,
and operation paths taken from the corresponding n8n node implementation. Keys
whose n8n node is a local filesystem reader, a database or messaging wire
protocol, an OAuth2 flow, a REST API that needs headers the shared connector
cannot set, or a REST API that injects credentials into the request body are
listed in :data:`UNSUPPORTED_BATCH16_KEYS` with the specific reason instead of
being given invented endpoints.
"""

from __future__ import annotations

from typing import Any

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)
from app.connectors.vendor_rest import VendorOperation, VendorRESTConnector, VendorSpec


BATCH16_CATALOG_KEYS = frozenset({
    "profit_well",
    "pushcut",
    "pushover",
    "quest_db",
    "quick_base",
    "quick_books",
    "quick_chart",
    "rabbit_m_q",
    "raindrop",
    "read_binary_file",
})

# Alias matching the shorter catalog-batch constant used by earlier batches.
BATCH16_KEYS = BATCH16_CATALOG_KEYS


VENDOR_SPECS: dict[str, VendorSpec] = {
    "profit_well": VendorSpec(
        key="profit_well",
        display_name="ProfitWell",
        description=(
            "ProfitWell company settings and recurring-revenue metrics. The API "
            "token is sent as the raw Authorization header value, matching the "
            "ProfitWell API."
        ),
        category="finance",
        base_url="https://api.profitwell.com/v2",
        auth_kind="header",
        auth_header="Authorization",
        credential_fields=("access_token",),
        operations={
            "get_settings": VendorOperation(
                "get_settings", "Get Settings", "GET", "/company/settings/",
                description="Get the company's ProfitWell account settings.",
            ),
            "get_metric": VendorOperation(
                "get_metric", "Get Metric", "GET", "/metrics/{type}", ("type",),
                description=(
                    "Get daily or monthly recurring-revenue metrics. Pass type as "
                    "daily or monthly, and pass month, metrics, and plan_id as query "
                    "parameters."
                ),
            ),
        },
    ),
    "pushcut": VendorSpec(
        key="pushcut",
        display_name="Pushcut",
        description="Pushcut notifications for iOS shortcuts and automations.",
        category="communication",
        base_url="https://api.pushcut.io/v1",
        auth_kind="header",
        auth_header="API-Key",
        credential_fields=("api_key",),
        operations={
            "send_notification": VendorOperation(
                "send_notification", "Send Notification", "POST",
                "/notifications/{notification_name}", ("notification_name",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send a notification. The body accepts devices, input, text, "
                    "and title as supported by Pushcut."
                ),
            ),
        },
    ),
    "quick_chart": VendorSpec(
        key="quick_chart",
        display_name="QuickChart",
        description=(
            "QuickChart chart images rendered from Chart.js configuration. No "
            "credentials are required; the chart definition is passed as the chart "
            "query parameter. Image responses are returned in the data.text field "
            "when they are not JSON."
        ),
        category="analytics",
        base_url="https://quickchart.io",
        auth_kind="none",
        credential_fields=(),
        operations={
            "create_chart": VendorOperation(
                "create_chart", "Create Chart", "GET", "/chart", ("chart",),
                description=(
                    "Render a chart. Pass chart as a JSON string plus optional "
                    "backgroundColor, devicePixelRatio, format, height, horizontal, "
                    "and width query parameters."
                ),
            ),
        },
    ),
}


# Keys intentionally left out of build_batch16_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH16_KEYS: dict[str, str] = {
    "pushover": (
        "n8n's Pushover credential injects the application token into the JSON "
        "request body for POST calls (and only into the query string for GET "
        "calls), while messages must be sent with POST /1/messages.json. "
        "VendorRESTConnector's query auth can add the token only to the URL and it "
        "never injects credentials into a request body, so the push operation "
        "would not carry the token where Pushover expects it."
    ),
    "quest_db": (
        "n8n's QuestDB node opens a PostgreSQL wire-protocol connection with "
        "pg-promise. Its credentials are host, port, database, user, password, and "
        "SSL mode, and its operations execute SQL over TCP. QuestDB has no HTTP "
        "REST API for these operations, so VendorRESTConnector cannot run them."
    ),
    "quick_base": (
        "Quick Base's REST API requires both an Authorization header "
        "(QB-USER-TOKEN <userToken>) and a QB-Realm-Hostname header carrying the "
        "realm hostname. VendorRESTConnector can set only one fixed auth header and "
        "has no per-connector extra-header support, so it cannot supply the realm "
        "and Quick Base would reject every request."
    ),
    "quick_books": (
        "n8n's QuickBooks node uses the quickBooksOAuth2Api credential and calls "
        "requestOAuth2 for every operation. VendorRESTConnector has no OAuth2 "
        "authorization-code or token-refresh handling, and QuickBooks access tokens "
        "expire, so a static bearer token cannot be used."
    ),
    "rabbit_m_q": (
        "n8n's RabbitMQ node speaks AMQP over TCP through the amqplib client "
        "(publish, consume, and acknowledge messages). It has no HTTP REST API, so "
        "VendorRESTConnector cannot implement it."
    ),
    "raindrop": (
        "n8n's Raindrop node requires the raindropOAuth2Api OAuth2 credential and "
        "calls requestOAuth2 for every operation. VendorRESTConnector has no OAuth2 "
        "authorization-code or token-refresh support, so it cannot authenticate as "
        "the n8n node does."
    ),
    "read_binary_file": (
        "n8n's Read Binary File node reads a file from the local filesystem or a "
        "mounted path inside the n8n instance and returns its binary contents. It "
        "has no vendor host, credentials, or HTTP operations, so there is nothing "
        "for a VendorRESTConnector to call."
    ),
}


def _build_definition(spec: VendorSpec) -> ConnectorDefinitionV1:
    operations = {
        key: ConnectorOperationV1(
            connector_key=spec.key,
            connector_version="1.0.0",
            operation_key=key,
            operation_version="1.0.0",
            display_name=op.display_name,
            description=op.description or f"{op.display_name} for {spec.display_name}.",
            input_schema={
                "type": "object",
                "properties": {
                    "params": {"type": "object"},
                    "body": {"type": "object"},
                },
                "required": list(op.requires),
            },
            output_schema={"type": "object"},
            credential_require=spec.key,
            retryable=op.retryable,
            idempotency=op.idempotency,
            node_types=[spec.key],
        )
        for key, op in spec.operations.items()
    }
    credential_properties: dict[str, Any] = {
        field: {"type": "string", "title": field.replace("_", " ").title()}
        for field in spec.credential_fields
    }
    return ConnectorDefinitionV1(
        connector_key=spec.key,
        display_name=spec.display_name,
        description=spec.description,
        category=spec.category,
        connector_version="1.0.0",
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=operations,
        triggers={},
        credential_types={
            spec.key: CredentialTypeV1(
                type_key=spec.key,
                display_name=f"{spec.display_name} Credentials",
                description=f"Credentials for {spec.display_name}.",
                secret_fields=list(spec.credential_fields),
                validation_schema={"type": "object", "properties": credential_properties},
                encryption_required=True,
            )
        },
        metadata={
            "implementation": "native",
            "batch": "catalog_conversion_16",
        },
    )


def build_batch16_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 16 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
