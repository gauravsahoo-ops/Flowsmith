"""Native REST connectors for catalog conversion batch 15.

Each implemented connector uses a fixed vendor host (or a fixed tenant host
parameter), the auth contract of the matching n8n node, and operation paths
taken from that node. Keys whose n8n node needs OAuth2 token exchange or
injects credentials into a request body are listed in
:data:`UNSUPPORTED_BATCH15_KEYS` with the specific reason instead of being
given invented endpoints.

PagerDuty is implemented for its read operations only. The n8n node sends the
acting user's email in a ``From`` header for incident and note writes, which
the shared :class:`~app.connectors.vendor_rest.VendorRESTConnector` cannot set.
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


BATCH15_CATALOG_KEYS = frozenset({
    "oura",
    "pager_duty",
    "pay_pal",
    "peekalink",
    "perplexity",
    "phantombuster",
    "philips_hue",
    "plivo",
    "post_bin",
    "post_hog",
})

# Alias matching the shorter catalog-batch constant used by earlier batches.
BATCH15_KEYS = BATCH15_CATALOG_KEYS


VENDOR_SPECS: dict[str, VendorSpec] = {
    "oura": VendorSpec(
        key="oura",
        display_name="Oura",
        description=(
            "Oura personal profile and daily activity, readiness, and sleep "
            "summaries using a personal access token."
        ),
        category="productivity",
        base_url="https://api.ouraring.com/v2",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "get_profile": VendorOperation(
                "get_profile", "Get Profile", "GET", "/usercollection/personal_info",
                description="Get the user's personal information.",
            ),
            "get_activity_summary": VendorOperation(
                "get_activity_summary", "Get Activity Summary", "GET",
                "/usercollection/daily_activity",
                description=(
                    "Get daily activity summaries; pass start_date and end_date as "
                    "query parameters."
                ),
            ),
            "get_readiness_summary": VendorOperation(
                "get_readiness_summary", "Get Readiness Summary", "GET",
                "/usercollection/daily_readiness",
                description=(
                    "Get daily readiness summaries; pass start_date and end_date as "
                    "query parameters."
                ),
            ),
            "get_sleep_summary": VendorOperation(
                "get_sleep_summary", "Get Sleep Summary", "GET",
                "/usercollection/daily_sleep",
                description=(
                    "Get daily sleep summaries; pass start_date and end_date as "
                    "query parameters."
                ),
            ),
        },
    ),
    "pager_duty": VendorSpec(
        key="pager_duty",
        display_name="PagerDuty",
        description=(
            "PagerDuty incidents, incident notes, log entries, and users using a "
            "general-access API token. Read operations only: PagerDuty writes in the "
            "n8n node require the acting user's email in a From header, which "
            "VendorRESTConnector cannot set."
        ),
        category="productivity",
        base_url="https://api.pagerduty.com",
        auth_kind="header",
        auth_header="Authorization",
        auth_prefix="Token token=",
        credential_fields=("api_key",),
        operations={
            "get_incident": VendorOperation(
                "get_incident", "Get Incident", "GET", "/incidents/{incident_id}",
                ("incident_id",),
            ),
            "list_incidents": VendorOperation(
                "list_incidents", "List Incidents", "GET", "/incidents",
                description=(
                    "List incidents; pass statuses, urgencies, since, until, "
                    "user_ids, team_ids, include, sort_by, limit, or offset as query "
                    "parameters."
                ),
            ),
            "list_incident_notes": VendorOperation(
                "list_incident_notes", "List Incident Notes", "GET",
                "/incidents/{incident_id}/notes", ("incident_id",),
                description="List an incident's notes; pass limit or offset as query parameters.",
            ),
            "get_log_entry": VendorOperation(
                "get_log_entry", "Get Log Entry", "GET", "/log_entries/{log_entry_id}",
                ("log_entry_id",),
            ),
            "list_log_entries": VendorOperation(
                "list_log_entries", "List Log Entries", "GET", "/log_entries",
                description=(
                    "List log entries; pass since, until, is_overview, include, "
                    "team_ids, and time_zone as query parameters."
                ),
            ),
            "get_user": VendorOperation(
                "get_user", "Get User", "GET", "/users/{user_id}", ("user_id",),
            ),
        },
    ),
    "peekalink": VendorSpec(
        key="peekalink",
        display_name="Peekalink",
        description=(
            "Peekalink link previews and link-preview availability checks. The link "
            "URL is sent in the JSON request body."
        ),
        category="analytics",
        base_url="https://api.peekalink.io",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "preview": VendorOperation(
                "preview", "Preview Link", "POST", "/", (),
                retryable=False, idempotency="non_idempotent",
                description="Return a preview for a link; the body requires link.",
            ),
            "is_available": VendorOperation(
                "is_available", "Check Link Availability", "POST", "/is-available/", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Check whether a preview is available for a link; the body "
                    "requires link."
                ),
            ),
        },
    ),
    "perplexity": VendorSpec(
        key="perplexity",
        display_name="Perplexity",
        description=(
            "Perplexity Agent responses, text and contextualized embeddings, and "
            "ranked web search. The deprecated Sonar chat resource from older n8n "
            "versions is not exposed."
        ),
        category="ai",
        base_url="https://api.perplexity.ai",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "create_response": VendorOperation(
                "create_response", "Create Agent Response", "POST", "/v1/agent", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a response with the Agent API; the body accepts input, "
                    "model or preset, and agent options."
                ),
            ),
            "create_embedding": VendorOperation(
                "create_embedding", "Create Embedding", "POST", "/v1/embeddings", (),
                retryable=False, idempotency="non_idempotent",
                description="Generate text embeddings from a model and input array.",
            ),
            "create_contextualized_embedding": VendorOperation(
                "create_contextualized_embedding", "Create Contextualized Embedding",
                "POST", "/v1/contextualizedembeddings", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Generate context-aware embeddings; input is an array of documents, "
                    "each an array of paragraph strings."
                ),
            ),
            "search": VendorOperation(
                "search", "Search", "POST", "/search", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Return ranked web search results; the body requires query and "
                    "accepts the documented search filters."
                ),
            ),
        },
    ),
    "phantombuster": VendorSpec(
        key="phantombuster",
        display_name="PhantomBuster",
        description=(
            "PhantomBuster agents: list, inspect, read output, launch, and delete. "
            "The streaming launch-sync operation is not exposed because "
            "VendorRESTConnector cannot consume NDJSON streams."
        ),
        category="marketing",
        base_url="https://api.phantombuster.com/api/v2",
        auth_kind="header",
        auth_header="X-Phantombuster-Key",
        credential_fields=("api_key",),
        operations={
            "list_agents": VendorOperation(
                "list_agents", "List Agents", "GET", "/agents/fetch-all",
                description="List the agents in the current organization.",
            ),
            "get_agent": VendorOperation(
                "get_agent", "Get Agent", "GET", "/agents/fetch",
                description="Get an agent; pass its id in payload.params.",
            ),
            "get_agent_output": VendorOperation(
                "get_agent_output", "Get Agent Output", "GET", "/agents/fetch-output",
                description=(
                    "Get the most recent container output for an agent; pass id and "
                    "optional prevContainerId, prevStatus, or prevRuntimeEventIndex in "
                    "payload.params."
                ),
            ),
            "launch_agent": VendorOperation(
                "launch_agent", "Launch Agent", "POST", "/agents/launch", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Add an agent to the launch queue; the body accepts id, arguments, "
                    "bonusArgument, and launch options."
                ),
            ),
            "delete_agent": VendorOperation(
                "delete_agent", "Delete Agent", "POST", "/agents/delete", (),
                retryable=False, idempotency="non_idempotent",
                description="Delete an agent; the body requires id.",
            ),
        },
    ),
    "plivo": VendorSpec(
        key="plivo",
        display_name="Plivo",
        description=(
            "Plivo SMS, MMS, and voice calls using Basic auth. The Plivo auth ID is "
            "both the Basic-auth username and the account path segment."
        ),
        category="communication",
        base_url="https://api.plivo.com/v1/Account/{auth_id}",
        auth_kind="basic",
        basic_user_field="auth_id",
        basic_password_field="auth_token",
        credential_fields=("auth_id", "auth_token"),
        extra_required=("auth_id",),
        operations={
            "send_sms": VendorOperation(
                "send_sms", "Send SMS", "POST", "/Message/", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send an SMS; the body accepts src, dst, and text plus optional "
                    "delivery options."
                ),
            ),
            "send_mms": VendorOperation(
                "send_mms", "Send MMS", "POST", "/Message/", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send an MMS; the body accepts src, dst, text, type=mms, and "
                    "media_urls."
                ),
            ),
            "make_call": VendorOperation(
                "make_call", "Make Call", "POST", "/Call/", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create an outbound call; the body accepts from, to, answer_url, "
                    "and answer_method."
                ),
            ),
        },
    ),
    "post_bin": VendorSpec(
        key="post_bin",
        display_name="PostBin",
        description=(
            "PostBin throwaway request bins for testing webhooks and HTTP clients. "
            "No credentials are required; bins expire after 30 minutes."
        ),
        category="developer",
        base_url="https://www.postb.in",
        auth_kind="none",
        credential_fields=(),
        operations={
            "create_bin": VendorOperation(
                "create_bin", "Create Bin", "POST", "/api/bin", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "get_bin": VendorOperation(
                "get_bin", "Get Bin", "GET", "/api/bin/{bin_id}", ("bin_id",),
            ),
            "delete_bin": VendorOperation(
                "delete_bin", "Delete Bin", "DELETE", "/api/bin/{bin_id}", ("bin_id",),
            ),
            "get_request": VendorOperation(
                "get_request", "Get Request", "GET",
                "/api/bin/{bin_id}/req/{request_id}", ("bin_id", "request_id"),
            ),
            "remove_first_request": VendorOperation(
                "remove_first_request", "Remove First Request", "GET",
                "/api/bin/{bin_id}/req/shift", ("bin_id",),
            ),
            "send_request": VendorOperation(
                "send_request", "Send Request", "POST", "/{bin_id}", ("bin_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send a test request to a bin; the body is forwarded to the bin."
                ),
            ),
        },
    ),
}


# Keys intentionally left out of build_batch15_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH15_KEYS: dict[str, str] = {
    "pay_pal": (
        "n8n's PayPal node uses the payPalApi credential (clientId, secret, env) and "
        "exchanges it for a short-lived OAuth2 access token by POSTing "
        "grant_type=client_credentials to /v1/oauth2/token on the sandbox or live "
        "host for every request. VendorRESTConnector has no client-credentials token "
        "exchange or refresh flow and cannot select the sandbox/live host from "
        "credential data, so a static bearer token would be missing or expired."
    ),
    "philips_hue": (
        "n8n's Philips Hue node authenticates with the philipsHueOAuth2Api "
        "credential through requestOAuth2 with tokenType Bearer and calls the cloud "
        "route at https://api.meethue.com/route. It also auto-provisions a whitelist "
        "username by enabling the bridge link button and posting to /api. "
        "VendorRESTConnector has no OAuth2 authorization-code flow, refresh, or "
        "multi-step user provisioning, so its requests would be unauthenticated."
    ),
    "post_hog": (
        "n8n's PostHog node reads both the project API key and the base URL from the "
        "postHogApi credential, then injects the key into the JSON request body as "
        "api_key for every /capture and /batch call. VendorRESTConnector never adds "
        "credentials to a request body and requires a fixed host, so it cannot "
        "authenticate PostHog capture calls or follow a credential-supplied "
        "self-hosted PostHog URL."
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
            "batch": "catalog_conversion_15",
        },
    )


def build_batch15_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 15 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
