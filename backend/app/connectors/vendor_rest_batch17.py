"""Native REST connectors for catalog conversion batch 17.

Each connector uses a fixed vendor host, an explicit auth contract, and
operation paths taken from the corresponding n8n node implementation. Keys
whose n8n node is a local filesystem/transform action, fetches an arbitrary
URL, or requires an authentication protocol the shared
:class:`~app.connectors.vendor_rest.VendorRESTConnector` cannot perform are
listed in :data:`UNSUPPORTED_BATCH17_KEYS` with the specific reason instead of
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


BATCH17_CATALOG_KEYS = frozenset({
    "read_binary_files",
    "read_p_d_f",
    "read_write_file",
    "reddit",
    "remove_duplicates",
    "rocketchat",
    "rss_feed_read",
    "rundeck",
    "salesmate",
    "sea_table",
})

# Alias matching the shorter catalog-batch constant used by earlier batches.
BATCH17_KEYS = BATCH17_CATALOG_KEYS


VENDOR_SPECS: dict[str, VendorSpec] = {
    "rundeck": VendorSpec(
        key="rundeck",
        display_name="Rundeck",
        description=(
            "Rundeck job execution and metadata on a self-hosted instance. "
            "Provide the instance hostname, including a port when it is not 443."
        ),
        category="developer",
        base_url="https://{host}",
        auth_kind="header",
        auth_header="X-Rundeck-Auth-Token",
        credential_fields=("api_key",),
        extra_required=("host",),
        operations={
            "execute_job": VendorOperation(
                "execute_job", "Execute Job", "POST", "/api/14/job/{job_id}/run",
                ("job_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Execute a Rundeck job. The body accepts argString; pass filter "
                    "as a query parameter."
                ),
            ),
            "get_job_metadata": VendorOperation(
                "get_job_metadata", "Get Job Metadata", "GET",
                "/api/18/job/{job_id}/info", ("job_id",),
                description="Get metadata for a job from Rundeck's API v18.",
            ),
        },
    ),
}


# Keys intentionally left out of build_batch17_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH17_KEYS: dict[str, str] = {
    "read_binary_files": (
        "n8n's Read Binary Files node reads files from the filesystem of the "
        "machine running n8n: it expands a glob with globWithDeadline and opens "
        "each match through helpers.createReadStream, then emits n8n binary data. "
        "It has no vendor host, credential, or REST endpoint, so VendorRESTConnector "
        "cannot perform this local file read."
    ),
    "read_p_d_f": (
        "n8n's Read PDF node calls the local extractDataFromPDF helper to decrypt "
        "and extract text from a PDF held in an input binary property. It issues no "
        "HTTP request and has no vendor host, credential, or endpoint, so "
        "VendorRESTConnector cannot run PDF extraction."
    ),
    "read_write_file": (
        "n8n's Read/Write Files from Disk node reads and writes files on the "
        "computer running n8n using its local filesystem helpers, resolving paths "
        "and streaming file contents. It has no vendor host, credential, or REST "
        "endpoint, so VendorRESTConnector cannot perform local file I/O."
    ),
    "reddit": (
        "n8n's Reddit node sends authenticated profile, post, and postComment "
        "operations to https://oauth.reddit.com through requestOAuth2 with the "
        "redditOAuth2Api credential, which requires an OAuth2 authorization-code "
        "flow and token refresh. VendorRESTConnector only supports static "
        "credentials and has no OAuth2 exchange or refresh, so Reddit actions "
        "cannot authenticate."
    ),
    "remove_duplicates": (
        "n8n's Remove Duplicates node is a local transform that compares input "
        "items across the current or previous executions and drops items with "
        "matching field values. It has no vendor host, credentials, or HTTP "
        "endpoint, so there is nothing for a VendorRESTConnector to call."
    ),
    "rocketchat": (
        "n8n's RocketChat node authenticates with two headers, X-Auth-Token "
        "(authKey) and X-User-Id (userId), against a user-supplied domain under "
        "/api/v1 (chat.postMessage, subscriptions.get, subscriptions.read, and "
        "dm.messages). VendorRESTConnector can set only one auth header and has no "
        "way to supply X-User-Id, so every RocketChat request would be "
        "unauthenticated."
    ),
    "rss_feed_read": (
        "n8n's RSS Read node fetches an arbitrary URL supplied at execution time, so "
        "it has no fixed vendor host, then parses the XML response with rss-parser. "
        "VendorRESTConnector requires a fixed host and operation path and handles "
        "responses as JSON or plain text rather than feed XML, so there is no "
        "non-invented fixed endpoint for this connector."
    ),
    "salesmate": (
        "n8n's Salesmate node sends both a sessionToken header (the credential's "
        "session token) and an x-linkname header (the tenant URL) to "
        "https://apis.salesmate.io. VendorRESTConnector can set only one auth header "
        "and cannot add the required x-linkname tenant header, so Salesmate requests "
        "would be rejected as unauthenticated."
    ),
    "sea_table": (
        "n8n's SeaTable v2 node first exchanges the base API token at "
        "GET /api/v2.1/dtable/app-access-token/ for a short-lived base access_token "
        "and dtable_uuid, then sends Authorization: Token {access_token} to "
        "/api-gateway/api/v2/dtables/{dtable_uuid}/... . VendorRESTConnector has no "
        "pre-authentication or session exchange and cannot derive dtable_uuid, so it "
        "cannot address SeaTable rows."
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
            "batch": "catalog_conversion_17",
        },
    )


def build_batch17_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 17 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
