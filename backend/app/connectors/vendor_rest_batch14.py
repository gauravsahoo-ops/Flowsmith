"""Native REST connectors for catalog conversion batch 14.

Each connector uses a fixed vendor host, an explicit auth contract, and
operation paths taken from the corresponding n8n node implementation. Keys
whose n8n node is a local transform, a database wire protocol, or a protocol
the shared :class:`~app.connectors.vendor_rest.VendorRESTConnector` cannot
authenticate are listed in :data:`UNSUPPORTED_BATCH14_KEYS` with the specific
reason instead of being given invented endpoints.
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


BATCH14_CATALOG_KEYS = frozenset({
    "my_sql",
    "n8n",
    "netscaler_adc",
    "next_cloud",
    "no_op",
    "odoo",
    "one_simple_api",
    "open_thesaurus",
    "open_weather_map",
    "orbit",
})


VENDOR_SPECS: dict[str, VendorSpec] = {
    "n8n": VendorSpec(
        key="n8n",
        display_name="n8n",
        description=(
            "n8n workflows, executions, credentials, projects, and audit log on a "
            "self-hosted instance. Provide the hostname of the instance; the public "
            "API v1 prefix is appended to it."
        ),
        category="developer",
        base_url="https://{host}/api/v1",
        auth_kind="header",
        auth_header="X-N8N-API-KEY",
        credential_fields=("api_key",),
        extra_required=("host",),
        operations={
            "generate_audit": VendorOperation(
                "generate_audit", "Generate Audit", "POST", "/audit", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Generate an audit report. The body accepts additionalOptions, "
                    "categories, and daysAbandonedWorkflow."
                ),
            ),
            "create_credential": VendorOperation(
                "create_credential", "Create Credential", "POST", "/credentials", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a credential with name, type, and data.",
            ),
            "delete_credential": VendorOperation(
                "delete_credential", "Delete Credential", "DELETE",
                "/credentials/{credential_id}", ("credential_id",),
            ),
            "get_credential_schema": VendorOperation(
                "get_credential_schema", "Get Credential Schema", "GET",
                "/credentials/schema/{credential_type_name}", ("credential_type_name",),
            ),
            "get_execution": VendorOperation(
                "get_execution", "Get Execution", "GET", "/executions/{execution_id}",
                ("execution_id",),
            ),
            "list_executions": VendorOperation(
                "list_executions", "List Executions", "GET", "/executions",
                description=(
                    "List executions; pass cursor, limit, status, workflowId, and "
                    "includeData as query parameters."
                ),
            ),
            "delete_execution": VendorOperation(
                "delete_execution", "Delete Execution", "DELETE", "/executions/{execution_id}",
                ("execution_id",),
            ),
            "add_project_user": VendorOperation(
                "add_project_user", "Add Project User", "POST",
                "/projects/{project_id}/users", ("project_id",),
                retryable=False, idempotency="non_idempotent",
                description="Add a user to a project with relations and role.",
            ),
            "create_workflow": VendorOperation(
                "create_workflow", "Create Workflow", "POST", "/workflows", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a workflow from a workflow object.",
            ),
            "list_workflows": VendorOperation(
                "list_workflows", "List Workflows", "GET", "/workflows",
                description=(
                    "List workflows; pass active, tags, name, projectId, limit, and "
                    "cursor as query parameters."
                ),
            ),
            "activate_workflow": VendorOperation(
                "activate_workflow", "Activate Workflow", "POST",
                "/workflows/{workflow_id}/activate", ("workflow_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "deactivate_workflow": VendorOperation(
                "deactivate_workflow", "Deactivate Workflow", "POST",
                "/workflows/{workflow_id}/deactivate", ("workflow_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_workflow": VendorOperation(
                "delete_workflow", "Delete Workflow", "DELETE", "/workflows/{workflow_id}",
                ("workflow_id",),
            ),
            "get_workflow": VendorOperation(
                "get_workflow", "Get Workflow", "GET", "/workflows/{workflow_id}",
                ("workflow_id",),
            ),
            "get_workflow_version": VendorOperation(
                "get_workflow_version", "Get Workflow Version", "GET",
                "/workflows/{workflow_id}/{version_id}", ("workflow_id", "version_id"),
            ),
            "update_workflow": VendorOperation(
                "update_workflow", "Update Workflow", "PUT", "/workflows/{workflow_id}",
                ("workflow_id",),
                description="Update a workflow from a workflow object.",
            ),
        },
    ),
    "netscaler_adc": VendorSpec(
        key="netscaler_adc",
        display_name="Netscaler ADC",
        description=(
            "Netscaler ADC NITRO system files and certificates on a self-hosted "
            "appliance. Provide the appliance hostname, including a port when it is "
            "not 443."
        ),
        category="developer",
        base_url="https://{host}/nitro/v1",
        auth_kind="basic",
        basic_user_field="username",
        basic_password_field="password",
        credential_fields=("username", "password"),
        extra_required=("host",),
        operations={
            "upload_file": VendorOperation(
                "upload_file", "Upload File", "POST", "/config/systemfile", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Upload a file. The body must contain a systemfile object with "
                    "filename, filecontent (Base64), filelocation, and fileencoding."
                ),
            ),
            "delete_file": VendorOperation(
                "delete_file", "Delete File", "DELETE",
                "/config/systemfile?args=filename:{file_name},filelocation:{file_location}",
                ("file_name", "file_location"),
            ),
            "download_file": VendorOperation(
                "download_file", "Download File", "GET",
                "/config/systemfile?args=filename:{file_name},filelocation:{file_location}",
                ("file_name", "file_location"),
                description="Download a file; the NITRO response contains its Base64 content.",
            ),
            "create_certificate": VendorOperation(
                "create_certificate", "Create Certificate", "POST",
                "/config/sslcert?action=create", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a certificate. The body must contain an sslcert object "
                    "with the certificate and key file details."
                ),
            ),
            "install_certificate": VendorOperation(
                "install_certificate", "Install Certificate", "POST",
                "/config/sslcertkey", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Install a certificate-key pair. The body must contain an "
                    "sslcertkey object."
                ),
            ),
        },
    ),
    "one_simple_api": VendorSpec(
        key="one_simple_api",
        display_name="One Simple API",
        description=(
            "One Simple API utilities for websites, social profiles, exchange rates, "
            "and common data transformations."
        ),
        category="productivity",
        base_url="https://onesimpleapi.com/api",
        auth_kind="query",
        query_param="token",
        credential_fields=("api_key",),
        operations={
            "generate_pdf": VendorOperation(
                "generate_pdf", "Generate PDF", "GET", "/pdf?output=json",
                description=(
                    "Generate a PDF from a webpage. Pass url, page, and force as "
                    "query parameters; download the returned url separately."
                ),
            ),
            "take_screenshot": VendorOperation(
                "take_screenshot", "Take Screenshot", "GET", "/screenshot?output=json",
                description=(
                    "Screenshot a webpage. Pass url, screen, fullpage, and force as "
                    "query parameters; download the returned url separately."
                ),
            ),
            "get_seo_data": VendorOperation(
                "get_seo_data", "Get SEO Data", "GET", "/page_info?output=json",
                description="Get SEO information for a webpage; pass url and headers.",
            ),
            "get_instagram_profile": VendorOperation(
                "get_instagram_profile", "Get Instagram Profile", "GET",
                "/instagram_profile?output=json",
                description="Get an Instagram profile; pass profile.",
            ),
            "get_spotify_artist_profile": VendorOperation(
                "get_spotify_artist_profile", "Get Spotify Artist Profile", "GET",
                "/spotify_profile?output=json",
                description="Get a Spotify artist profile; pass profile.",
            ),
            "get_exchange_rate": VendorOperation(
                "get_exchange_rate", "Get Exchange Rate", "GET", "/exchange_rate?output=json",
                description="Convert between currencies; pass from_currency, to_currency, and from_value.",
            ),
            "get_image_metadata": VendorOperation(
                "get_image_metadata", "Get Image Metadata", "GET", "/image_info?output=json",
                description="Get image metadata; pass url and raw.",
            ),
            "validate_email": VendorOperation(
                "validate_email", "Validate Email", "GET", "/email?output=json",
                description="Validate an email address; pass email.",
            ),
            "expand_url": VendorOperation(
                "expand_url", "Expand URL", "GET", "/unshorten?output=json",
                description="Expand a shortened URL; pass url.",
            ),
            "generate_qr_code": VendorOperation(
                "generate_qr_code", "Generate QR Code", "GET", "/qr_code?output=json",
                description=(
                    "Generate a QR code. Pass message, size, and format as query "
                    "parameters; download the returned url separately."
                ),
            ),
        },
    ),
    "open_thesaurus": VendorSpec(
        key="open_thesaurus",
        display_name="OpenThesaurus",
        description="OpenThesaurus German-language synonym search. No credentials are required.",
        category="productivity",
        base_url="https://www.openthesaurus.de",
        auth_kind="none",
        credential_fields=(),
        operations={
            "get_synonyms": VendorOperation(
                "get_synonyms", "Get Synonyms", "GET",
                "/synonyme/search?format=application/json",
                description=(
                    "Get synonyms for a German word. Pass q as a query parameter, "
                    "plus optional baseform, similar, startswith, substring, "
                    "substringFromResults, substringMaxResults, subsynsets, and "
                    "supersynsets."
                ),
            ),
        },
    ),
    "open_weather_map": VendorSpec(
        key="open_weather_map",
        display_name="OpenWeatherMap",
        description="OpenWeatherMap current weather and five-day forecasts.",
        category="analytics",
        base_url="https://api.openweathermap.org/data/2.5",
        auth_kind="query",
        query_param="APPID",
        credential_fields=("api_key",),
        operations={
            "get_current_weather": VendorOperation(
                "get_current_weather", "Get Current Weather", "GET", "/weather",
                description=(
                    "Get current weather. Pass q, id, lat/lon, or zip as a location "
                    "and optionally units and lang as query parameters."
                ),
            ),
            "get_forecast": VendorOperation(
                "get_forecast", "Get 5 Day Forecast", "GET", "/forecast",
                description=(
                    "Get a five-day forecast. Pass q, id, lat/lon, or zip as a "
                    "location and optionally units and lang as query parameters."
                ),
            ),
        },
    ),
    "orbit": VendorSpec(
        key="orbit",
        display_name="Orbit",
        description=(
            "Orbit community analytics members, activities, notes, and posts. The "
            "upstream Orbit service was shut down, so this connector is kept for "
            "compatibility with existing workflows."
        ),
        category="analytics",
        base_url="https://app.orbit.love/api/v1",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "create_activity": VendorOperation(
                "create_activity", "Create Activity", "POST",
                "/{workspace_id}/members/{member_id}/activities",
                ("workspace_id", "member_id"),
                retryable=False, idempotency="non_idempotent",
                description="Create an activity for a member with title and optional details.",
            ),
            "list_activities": VendorOperation(
                "list_activities", "List Activities", "GET", "/{workspace_id}/activities",
                ("workspace_id",),
                description="List workspace activities; pass limit and filters as query parameters.",
            ),
            "list_member_activities": VendorOperation(
                "list_member_activities", "List Member Activities", "GET",
                "/{workspace_id}/members/{member_id}/activities",
                ("workspace_id", "member_id"),
                description="List a member's activities; pass limit as a query parameter.",
            ),
            "upsert_member": VendorOperation(
                "upsert_member", "Create or Update Member", "POST", "/{workspace_id}/members",
                ("workspace_id",),
                retryable=False, idempotency="non_idempotent",
                description="Create or update a member from member and identity objects.",
            ),
            "delete_member": VendorOperation(
                "delete_member", "Delete Member", "DELETE",
                "/{workspace_id}/members/{member_id}", ("workspace_id", "member_id"),
            ),
            "get_member": VendorOperation(
                "get_member", "Get Member", "GET", "/{workspace_id}/members/{member_id}",
                ("workspace_id", "member_id"),
                description="Get a member; pass resolveIdentities as a query parameter.",
            ),
            "list_members": VendorOperation(
                "list_members", "List Members", "GET", "/{workspace_id}/members",
                ("workspace_id",),
                description="List workspace members; pass limit, sort, and direction as query parameters.",
            ),
            "lookup_member": VendorOperation(
                "lookup_member", "Lookup Member", "GET", "/{workspace_id}/members/find",
                ("workspace_id",),
                description="Look up a member by source, username or uid, or email.",
            ),
            "update_member": VendorOperation(
                "update_member", "Update Member", "PUT", "/{workspace_id}/members/{member_id}",
                ("workspace_id", "member_id"),
                description="Update member attributes.",
            ),
            "create_note": VendorOperation(
                "create_note", "Create Note", "POST",
                "/{workspace_id}/members/{member_id}/notes", ("workspace_id", "member_id"),
                retryable=False, idempotency="non_idempotent",
                description="Create a note for a member; the body accepts body.",
            ),
            "list_notes": VendorOperation(
                "list_notes", "List Notes", "GET",
                "/{workspace_id}/members/{member_id}/notes", ("workspace_id", "member_id"),
                description="List a member's notes; pass limit and resolveMember as query parameters.",
            ),
            "update_note": VendorOperation(
                "update_note", "Update Note", "PUT",
                "/{workspace_id}/members/{member_id}/notes/{note_id}",
                ("workspace_id", "member_id", "note_id"),
                description="Update a note; the body accepts body.",
            ),
            "create_post": VendorOperation(
                "create_post", "Create Post", "POST",
                "/{workspace_id}/members/{member_id}/activities/",
                ("workspace_id", "member_id"),
                retryable=False, idempotency="non_idempotent",
                description="Create a post activity from a url and optional occurred_at.",
            ),
            "list_posts": VendorOperation(
                "list_posts", "List Posts", "GET", "/{workspace_id}/activities?type=content",
                ("workspace_id",),
                description="List workspace posts. The content activity type is fixed.",
            ),
            "delete_post": VendorOperation(
                "delete_post", "Delete Post", "DELETE",
                "/{workspace_id}/members/{member_id}/activities/{post_id}",
                ("workspace_id", "member_id", "post_id"),
            ),
        },
    ),
}


# Keys intentionally left out of build_batch14_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH14_KEYS: dict[str, str] = {
    "my_sql": (
        "n8n's MySQL node opens a MySQL connection with the mysql2 driver and "
        "speaks the MySQL wire protocol over TCP, not HTTP. Its credentials are "
        "host, port, database, user, password, and SSL options, and its operations "
        "build SQL against that connection. VendorRESTConnector only issues HTTP(S) "
        "requests to a fixed base URL, so it cannot run MySQL queries."
    ),
    "next_cloud": (
        "n8n's Nextcloud node uses WebDAV and OCS rather than a JSON REST API. File "
        "and folder operations use PROPFIND, MKCOL, COPY, and MOVE with XML bodies "
        "and Destination/Depth headers, while sharing and user operations require "
        "the OCS-APIRequest header plus form-encoded bodies. VendorRESTConnector has "
        "no per-operation header support and cannot send WebDAV/OCS payloads, so it "
        "cannot implement this protocol."
    ),
    "no_op": (
        "The No Operation node is a local pass-through that returns its input items "
        "unchanged. It has no vendor host, credentials, or REST endpoint, so there "
        "is nothing for a VendorRESTConnector to call."
    ),
    "odoo": (
        "n8n's Odoo node exposes model methods at POST /json/2/{model}/{method} with "
        "a mandatory X-Odoo-Database header under the recommended API-key auth, and "
        "its legacy auth first calls POST /jsonrpc common/login to obtain a user ID "
        "before object/execute calls. VendorRESTConnector supports neither "
        "per-operation headers nor a login/session exchange, so Odoo requests would "
        "be unauthenticated or addressed to the wrong database."
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
            "batch": "catalog_conversion_14",
        },
    )


def build_batch14_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 14 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
