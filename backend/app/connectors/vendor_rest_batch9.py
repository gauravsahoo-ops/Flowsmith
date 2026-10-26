"""Native REST connectors for catalog conversion batch 9.

Hacker News, Home Assistant, Humantic AI, and Hunter expose fixed HTTPS hosts
and an auth scheme that :class:`~app.connectors.vendor_rest.VendorRESTConnector`
implements (none, bearer, or query-string API key). The remaining catalog keys
in this batch require OAuth2 token exchange, run entirely local transforms, or
are routing/logic nodes. They are listed in
:data:`UNSUPPORTED_BATCH9_KEYS` with the specific reason and are not replaced
with invented endpoints.
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

BATCH9_CATALOG_KEYS = frozenset({
    "hacker_news",
    "halo_p_s_a",
    "help_scout",
    "high_level",
    "home_assistant",
    "html",
    "humantic_ai",
    "hunter",
    "i_calendar",
    "if",
})

# Keys intentionally left out of build_batch9_connectors(). Keeping the
# reasons next to the implemented specs makes the gap explicit instead of
# shipping connector definitions whose operations cannot actually run.
UNSUPPORTED_BATCH9_KEYS: dict[str, str] = {
    "halo_p_s_a": (
        "n8n's HaloPSA node performs an OAuth2 client-credentials token exchange "
        "against a tenant-specific auth URL and then calls a customer-supplied "
        "resourceApiUrl. VendorRESTConnector only accepts a static bearer or API "
        "key and a fixed base URL; it has no OAuth2 token acquisition, refresh, or "
        "per-tenant host handling."
    ),
    "help_scout": (
        "n8n authenticates Help Scout through the 'helpScoutOAuth2Api' credential "
        "using requestOAuth2 (authorization-code OAuth2 with token refresh). "
        "VendorRESTConnector supports only a static bearer token and cannot perform "
        "the OAuth2 flow."
    ),
    "high_level": (
        "n8n's HighLevel v2 node calls the API through 'highLevelOAuth2Api' and "
        "adds a mandatory Version: 2021-07-28 header to every request. It also uses "
        "location-scoped OAuth2 token data. VendorRESTConnector has no OAuth2 "
        "authorization-code flow, refresh, location-scoped token handling, or "
        "per-operation header support."
    ),
    "html": (
        "n8n's HTML node is a local transform: it parses or builds HTML with cheerio "
        "and never calls a vendor HTTP API. It has no host, credentials, or REST "
        "operations for VendorRESTConnector."
    ),
    "i_calendar": (
        "n8n's iCalendar node is a local transform that generates an ICS event file "
        "in memory using the 'ics' library. It has no HTTP host or credentials and "
        "does not perform any REST request, so there is nothing for "
        "VendorRESTConnector to call."
    ),
    "if": (
        "n8n's If node is a local logic/routing node that evaluates conditions and "
        "routes items to true/false branches. It has no vendor HTTP host, "
        "credentials, or REST operations for VendorRESTConnector to call."
    ),
}

VENDOR_SPECS: dict[str, VendorSpec] = {
    "hacker_news": VendorSpec(
        key="hacker_news",
        display_name="Hacker News",
        description=(
            "Hacker News search, articles, and user profiles through the public "
            "Algolia HN API. No credentials are required."
        ),
        category="communication",
        base_url="https://hn.algolia.com/api/v1",
        auth_kind="none",
        credential_fields=(),
        operations={
            "search": VendorOperation(
                "search", "Search Items", "GET", "/search",
                description=(
                    "Search Hacker News stories and comments. Pass query, tags, "
                    "hitsPerPage, page, and numericFilters in payload.params."
                ),
            ),
            "get_article": VendorOperation(
                "get_article", "Get Article", "GET", "/items/{article_id}",
                ("article_id",),
            ),
            "get_user": VendorOperation(
                "get_user", "Get User", "GET", "/users/{username}", ("username",),
            ),
        },
    ),
    "home_assistant": VendorSpec(
        key="home_assistant",
        display_name="Home Assistant",
        description=(
            "Home Assistant configuration, services, states, events, logs, and "
            "templates on a self-hosted instance. The host value must be the "
            "HTTPS hostname, including a port when it is not 443."
        ),
        category="productivity",
        base_url="https://{host}/api",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("host",),
        operations={
            "get_config": VendorOperation("get_config", "Get Configuration", "GET", "/config"),
            "check_config": VendorOperation(
                "check_config", "Check Configuration", "POST",
                "/config/core/check_config",
                retryable=True, idempotency="idempotent",
            ),
            "list_services": VendorOperation(
                "list_services", "List Services", "GET", "/services",
            ),
            "call_service": VendorOperation(
                "call_service", "Call Service", "POST", "/services/{domain}/{service}",
                ("domain", "service"), retryable=False, idempotency="non_idempotent",
                description="Call a service; service data goes in payload.body.",
            ),
            "list_states": VendorOperation("list_states", "List States", "GET", "/states"),
            "get_state": VendorOperation(
                "get_state", "Get State", "GET", "/states/{entity_id}", ("entity_id",),
            ),
            "upsert_state": VendorOperation(
                "upsert_state", "Upsert State", "POST", "/states/{entity_id}",
                ("entity_id",), retryable=False, idempotency="non_idempotent",
                description="Set an entity state; body is {\"state\": ..., \"attributes\": {...}}.",
            ),
            "list_events": VendorOperation("list_events", "List Events", "GET", "/events"),
            "create_event": VendorOperation(
                "create_event", "Create Event", "POST", "/events/{event_type}",
                ("event_type",), retryable=False, idempotency="non_idempotent",
                description="Fire an event; event data goes in payload.body.",
            ),
            "get_error_log": VendorOperation(
                "get_error_log", "Get Error Log", "GET", "/error_log",
            ),
            "get_logbook": VendorOperation(
                "get_logbook", "Get Logbook", "GET", "/logbook",
                description="Pass entity and end_time in payload.params.",
            ),
            "get_logbook_since": VendorOperation(
                "get_logbook_since", "Get Logbook Since", "GET", "/logbook/{start_time}",
                ("start_time",),
                description="Pass entity and end_time in payload.params.",
            ),
            "render_template": VendorOperation(
                "render_template", "Render Template", "POST", "/template", (),
                retryable=True, idempotency="idempotent",
                description="Render a Home Assistant template; body is {\"template\": ...}.",
            ),
        },
    ),
    "humantic_ai": VendorSpec(
        key="humantic_ai",
        display_name="Humantic AI",
        description=(
            "Humantic AI personality profiles from LinkedIn URLs, email addresses, "
            "or supplied text. The API key is sent as the 'apikey' query parameter."
        ),
        category="analytics",
        base_url="https://api.humantic.ai/v1",
        auth_kind="query",
        query_param="apikey",
        credential_fields=("api_key",),
        operations={
            "create_profile": VendorOperation(
                "create_profile", "Create Profile", "GET", "/user-profile/create",
                ("userid",), retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a profile from a LinkedIn URL or email address. Pass "
                    "userid in payload.params; resume uploads are not exposed because "
                    "they require multipart form data."
                ),
            ),
            "get_profile": VendorOperation(
                "get_profile", "Get Profile", "GET", "/user-profile", ("userid",),
                description="Pass userid and optional persona in payload.params.",
            ),
            "update_profile": VendorOperation(
                "update_profile", "Update Profile", "POST",
                "/user-profile/create?userid={userid}", ("userid",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Update a profile created from a LinkedIn URL. The text goes in "
                    "payload.body as {\"text\": ...}; resume uploads are not exposed."
                ),
            ),
        },
    ),
    "hunter": VendorSpec(
        key="hunter",
        display_name="Hunter",
        description=(
            "Hunter domain search, email finder, and email verifier. The API key is "
            "sent as the 'api_key' query parameter."
        ),
        category="crm",
        base_url="https://api.hunter.io/v2",
        auth_kind="query",
        query_param="api_key",
        credential_fields=("api_key",),
        operations={
            "domain_search": VendorOperation(
                "domain_search", "Domain Search", "GET", "/domain-search", ("domain",),
                description="Pass domain plus optional filters and pagination in payload.params.",
            ),
            "email_finder": VendorOperation(
                "email_finder", "Email Finder", "GET", "/email-finder",
                ("domain", "first_name", "last_name"),
            ),
            "email_verifier": VendorOperation(
                "email_verifier", "Email Verifier", "GET", "/email-verifier", ("email",),
            ),
        },
    ),
}

# Keep BATCH9_KEYS aligned with the other catalog-conversion batches: it names
# every key in the batch, including the ones reported as unsupported. The
# runnable subset is exposed as BATCH9_IMPLEMENTED_KEYS for callers that need it.
BATCH9_KEYS = BATCH9_CATALOG_KEYS
BATCH9_IMPLEMENTED_KEYS = frozenset(VENDOR_SPECS)


def _title(field: str) -> str:
    return field.replace("_", " ").title()


def _credential_schema(spec: VendorSpec) -> dict[str, Any]:
    """Build the JSON schema shown for this connector's credential type."""
    properties = {
        field: {"type": "string", "title": _title(field), "format": "password"}
        for field in spec.credential_fields
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(spec.credential_fields),
    }


def _operation_definition(spec: VendorSpec, op: VendorOperation) -> ConnectorOperationV1:
    required_params = list(dict.fromkeys((*spec.extra_required, *op.requires)))
    param_properties = {name: {"type": "string"} for name in required_params}
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "params": {
                "type": "object",
                "properties": param_properties,
                "additionalProperties": True,
            },
            "body": {"type": "object", "additionalProperties": True},
            "timeout_seconds": {
                "type": "number",
                "minimum": 1,
                "maximum": 300,
                "default": 30,
            },
        },
    }
    if required_params:
        input_schema["properties"]["params"]["required"] = required_params
        input_schema["required"] = ["params"]
    return ConnectorOperationV1(
        connector_key=spec.key,
        connector_version="1.0.0",
        operation_key=op.key,
        operation_version="1.0.0",
        display_name=op.display_name,
        description=op.description or f"{op.display_name} for {spec.display_name}.",
        input_schema=input_schema,
        output_schema={"type": "object"},
        credential_require=spec.key,
        retryable=op.retryable,
        idempotency=op.idempotency,
        node_types=[spec.key],
    )


def _build_definition(spec: VendorSpec) -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=spec.key,
        display_name=spec.display_name,
        description=spec.description,
        category=spec.category,
        connector_version="1.0.0",
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations={
            key: _operation_definition(spec, op)
            for key, op in spec.operations.items()
        },
        triggers={},
        credential_types={
            spec.key: CredentialTypeV1(
                type_key=spec.key,
                display_name=f"{spec.display_name} Credentials",
                description=f"Credentials for {spec.display_name}.",
                secret_fields=list(spec.credential_fields),
                validation_schema=_credential_schema(spec),
                encryption_required=True,
            )
        },
        metadata={
            "implementation": "native",
            "batch": "catalog_conversion_9",
        },
    )


def build_batch9_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Return the batch 9 native connector/definition pairs that can run.

    Unsupported catalog keys are intentionally omitted; see
    :data:`UNSUPPORTED_BATCH9_KEYS` for the per-key reason.
    """
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
