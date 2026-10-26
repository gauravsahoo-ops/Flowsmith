"""Native REST connectors for catalog conversion batch 19.

Each implemented connector uses a fixed vendor host, an explicit auth contract,
and operation paths taken from the corresponding n8n node implementation. Keys
whose n8n node is a local transform, a canvas annotation, a binary file
converter, or requires an OAuth2 flow the shared
:class:`~app.connectors.vendor_rest.VendorRESTConnector` cannot perform are
listed in :data:`UNSUPPORTED_BATCH19_KEYS` with the specific reason instead of
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


BATCH19_CATALOG_KEYS = frozenset({
    "split_in_batches",
    "splunk",
    "spotify",
    "spreadsheet_file",
    "stackby",
    "sticky_note",
    "storyblok",
    "strapi",
    "strava",
    "summarize",
})

# Short alias kept alongside the descriptive name used by newer batches.
BATCH19_KEYS = BATCH19_CATALOG_KEYS


VENDOR_SPECS: dict[str, VendorSpec] = {
    "stackby": VendorSpec(
        key="stackby",
        display_name="Stackby",
        description="Stackby table rows and records in a stack.",
        category="database",
        base_url="https://stackby.com/api/betav1",
        auth_kind="header",
        auth_header="api-key",
        credential_fields=("api_key",),
        operations={
            "list_rows": VendorOperation(
                "list_rows", "List Rows", "GET",
                "/rowlist/{stack_id}/{table}", ("stack_id", "table"),
                description=(
                    "List rows from a table; pass view, maxrecord, offset, and other "
                    "Stackby query parameters as query parameters."
                ),
            ),
            "get_row": VendorOperation(
                "get_row", "Get Row", "GET",
                "/rowlist/{stack_id}/{table}?rowIds={row_id}",
                ("stack_id", "table", "row_id"),
                description=(
                    "Read rows by ID. The row_id value is sent as the rowIds query "
                    "parameter used by Stackby's row list endpoint."
                ),
            ),
            "append_rows": VendorOperation(
                "append_rows", "Append Rows", "POST",
                "/rowcreate/{stack_id}/{table}", ("stack_id", "table"),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Append rows to a table. The body accepts Stackby's records "
                    "array, for example {\"records\": [{\"field\": {\"Name\": \"Acme\"}}]}."
                ),
            ),
            "delete_rows": VendorOperation(
                "delete_rows", "Delete Rows", "DELETE",
                "/rowdelete/{stack_id}/{table}?rowIds={row_id}",
                ("stack_id", "table", "row_id"),
                description=(
                    "Delete rows by ID. The row_id value is sent as the rowIds query "
                    "parameter used by Stackby's row delete endpoint."
                ),
            ),
        },
    ),
    "storyblok": VendorSpec(
        key="storyblok",
        display_name="Storyblok",
        description=(
            "Storyblok Management API stories for a space, authenticated with a "
            "Storyblok personal access token."
        ),
        category="database",
        base_url="https://mapi.storyblok.com",
        auth_kind="header",
        auth_header="Authorization",
        credential_fields=("access_token",),
        operations={
            "get_story": VendorOperation(
                "get_story", "Get Story", "GET",
                "/v1/spaces/{space_id}/stories/{story_id}",
                ("space_id", "story_id"),
            ),
            "list_stories": VendorOperation(
                "list_stories", "List Stories", "GET",
                "/v1/spaces/{space_id}/stories", ("space_id",),
                description=(
                    "List stories in a space; pass page, per_page, starts_with, and "
                    "other Storyblok query parameters as query parameters."
                ),
            ),
            "delete_story": VendorOperation(
                "delete_story", "Delete Story", "DELETE",
                "/v1/spaces/{space_id}/stories/{story_id}",
                ("space_id", "story_id"),
            ),
            "publish_story": VendorOperation(
                "publish_story", "Publish Story", "GET",
                "/v1/spaces/{space_id}/stories/{story_id}/publish",
                ("space_id", "story_id"),
                description=(
                    "Publish a story; pass release_id and lang as query parameters "
                    "to target a release or a single language."
                ),
            ),
            "unpublish_story": VendorOperation(
                "unpublish_story", "Unpublish Story", "GET",
                "/v1/spaces/{space_id}/stories/{story_id}/unpublish",
                ("space_id", "story_id"),
            ),
        },
    ),
    "strapi": VendorSpec(
        key="strapi",
        display_name="Strapi",
        description=(
            "Strapi v4 content entries on a self-hosted instance. Provide the "
            "instance hostname without a URL scheme."
        ),
        category="database",
        base_url="https://{host}/api",
        auth_kind="bearer",
        credential_fields=("api_token",),
        extra_required=("host",),
        operations={
            "list_entries": VendorOperation(
                "list_entries", "List Entries", "GET",
                "/{content_type}", ("content_type",),
                description=(
                    "List entries for a content type; pass Strapi v4 pagination, "
                    "filters, sort, and populate query parameters as query parameters."
                ),
            ),
            "get_entry": VendorOperation(
                "get_entry", "Get Entry", "GET",
                "/{content_type}/{entry_id}", ("content_type", "entry_id"),
                description=(
                    "Get an entry; pass populate and fields as query parameters."
                ),
            ),
            "create_entry": VendorOperation(
                "create_entry", "Create Entry", "POST",
                "/{content_type}", ("content_type",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create an entry. The body must use Strapi v4's data envelope, "
                    "for example {\"data\": {\"title\": \"Hello\"}}."
                ),
            ),
            "update_entry": VendorOperation(
                "update_entry", "Update Entry", "PUT",
                "/{content_type}/{entry_id}", ("content_type", "entry_id"),
                description=(
                    "Update an entry. The body must use Strapi v4's data envelope, "
                    "for example {\"data\": {\"title\": \"Hello\"}}."
                ),
            ),
            "delete_entry": VendorOperation(
                "delete_entry", "Delete Entry", "DELETE",
                "/{content_type}/{entry_id}", ("content_type", "entry_id"),
            ),
        },
    ),
}


# Keys intentionally left out of build_batch19_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH19_KEYS: dict[str, str] = {
    "split_in_batches": (
        "n8n's Split In Batches node is a local flow-control transform that slices "
        "input items into batches and loops the rest of the workflow. It has no "
        "vendor host, credential, or REST endpoint, so there is nothing for a "
        "VendorRESTConnector to call."
    ),
    "splunk": (
        "n8n's Splunk node takes the complete instance base URL (protocol, domain, "
        "and port) plus a self-signed-certificate toggle from the splunkApi "
        "credential, sends request bodies as application/x-www-form-urlencoded "
        "forms (including the search job payload), and parses XML responses for its "
        "main endpoints. VendorRESTConnector sends JSON bodies, returns JSON or "
        "text, and cannot honor the per-credential TLS toggle, so it cannot "
        "reproduce Splunk's API contract without mis-encoding requests."
    ),
    "spotify": (
        "n8n's Spotify node authenticates exclusively through the spotifyOAuth2Api "
        "credential, which requires an OAuth2 authorization-code flow and automatic "
        "access-token refresh. VendorRESTConnector only supports static bearer, "
        "basic, header, and query credentials, so it cannot obtain or refresh a "
        "Spotify token."
    ),
    "spreadsheet_file": (
        "n8n's Spreadsheet File node converts spreadsheet binaries (CSV, XLSX, "
        "ODS) from an input binary property or local file and writes the result "
        "back to a binary property or the local filesystem. It has no vendor host, "
        "credential, or REST endpoint, so there is nothing for a "
        "VendorRESTConnector to call."
    ),
    "sticky_note": (
        "n8n's Sticky Note is a canvas annotation with no inputs or outputs. Its "
        "execute method only returns the unchanged input items and it has no vendor "
        "host, credential, or REST endpoint, so there is nothing for a "
        "VendorRESTConnector to call."
    ),
    "strava": (
        "n8n's Strava node authenticates exclusively through the stravaOAuth2Api "
        "credential, which requires an OAuth2 authorization-code flow and automatic "
        "access-token refresh, and its helper sends form-encoded request bodies. "
        "VendorRESTConnector supports only static credentials and JSON bodies, so it "
        "cannot authenticate or encode Strava requests."
    ),
    "summarize": (
        "n8n's Summarize node is a local aggregation transform that counts, sums, "
        "averages, concatenates, or otherwise reduces input items. It has no vendor "
        "host, credential, or REST endpoint, so there is nothing for a "
        "VendorRESTConnector to call."
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
            "batch": "catalog_conversion_19",
        },
    )


def build_batch19_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 19 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
