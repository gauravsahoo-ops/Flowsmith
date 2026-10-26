"""Native REST connectors for catalog conversion batch 8.

This batch keeps only vendors whose request contracts can actually be
honored by :class:`~app.connectors.vendor_rest.VendorRESTConnector`: a fixed
host, a supported auth kind, and operations that do not need per-request
signing or custom mandatory headers.

Catalog keys that require an OAuth token-exchange/refresh flow, Shared Key
signing, or mandatory version headers are listed in
:data:`UNSUPPORTED_BATCH8_KEYS` with the specific reason. They are not given
placeholder specs or invented endpoints.
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


BATCH8_CATALOG_KEYS = frozenset({
    "azure_storage",
    "beeminder",
    "bitwarden",
    "cisco_webex",
    "clearbit",
    "click_up",
    "clockify",
    "cloudflare",
    "cockpit",
    "convert_kit",
})

# Keys intentionally left out of build_batch8_connectors(). Keeping the
# reasons next to the implemented specs makes the gap explicit instead of
# shipping a connector definition whose operations cannot actually run.
UNSUPPORTED_BATCH8_KEYS: dict[str, str] = {
    "azure_storage": (
        "Azure Storage requires either Shared Key HMAC-SHA256 request signing or "
        "Microsoft Entra OAuth2 combined with an x-ms-version header of 2017-11-09 "
        "or newer. VendorRESTConnector has no request-signing auth kind and no "
        "per-operation header support, so every request would return "
        "AuthenticationFailed/InvalidHeaderValue. Blob and container writes also "
        "need query parameters on PUT/POST, which the shared connector sends as "
        "request bodies."
    ),
    "bitwarden": (
        "Bitwarden's public API uses OAuth2 client-credentials: the client ID and "
        "secret are exchanged at Bitwarden's identity endpoint for a short-lived "
        "bearer token. VendorRESTConnector has no token-exchange or refresh flow, and "
        "the n8n credential exposes only clientId/clientSecret. A static bearer "
        "credential would expire and cannot be honestly supported."
    ),
    "cisco_webex": (
        "Webex by Cisco requires OAuth2 authorization-code tokens issued by "
        "webexapis.com, including refresh. VendorRESTConnector cannot perform the "
        "authorization-code or refresh flow, and the n8n node uses its OAuth2 "
        "credential for every request. There is no supported static token contract."
    ),
}


VENDOR_SPECS: dict[str, VendorSpec] = {
    "beeminder": VendorSpec(
        key="beeminder",
        display_name="Beeminder",
        description="Beeminder goals, datapoints, and user records.",
        category="productivity",
        base_url="https://www.beeminder.com/api/v1",
        auth_kind="query",
        query_param="auth_token",
        credential_fields=("auth_token",),
        operations={
            "list_goals": VendorOperation("list_goals", "List Goals", "GET", "/users/me/goals.json"),
            "get_goal": VendorOperation(
                "get_goal", "Get Goal", "GET", "/users/me/goals/{goal_name}.json",
                ("goal_name",),
            ),
            "get_user": VendorOperation("get_user", "Get User", "GET", "/users/me.json"),
            "list_datapoints": VendorOperation(
                "list_datapoints", "List Datapoints", "GET",
                "/users/me/goals/{goal_name}/datapoints.json", ("goal_name",),
            ),
            "create_datapoint": VendorOperation(
                "create_datapoint", "Create Datapoint", "POST",
                "/users/me/goals/{goal_name}/datapoints.json", ("goal_name",),
                retryable=False, idempotency="non_idempotent",
            ),
            "cancel_step_down": VendorOperation(
                "cancel_step_down", "Cancel Step Down", "POST",
                "/users/me/goals/{goal_name}/cancel_stepdown.json", ("goal_name",),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "clearbit": VendorSpec(
        key="clearbit",
        display_name="Clearbit",
        description=(
            "Clearbit company enrichment. Clearbit serves company and person lookups "
            "from different fixed hosts, so only the company-stream host is implemented."
        ),
        category="crm",
        base_url="https://company-stream.clearbit.com",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "enrich_company": VendorOperation(
                "enrich_company", "Enrich Company", "GET", "/v2/companies/find",
                description="Pass domain as a query parameter.",
            ),
        },
    ),
    "click_up": VendorSpec(
        key="click_up",
        display_name="ClickUp",
        description="ClickUp teams, spaces, lists, and tasks.",
        category="productivity",
        base_url="https://api.clickup.com/api/v2",
        auth_kind="header",
        auth_header="Authorization",
        credential_fields=("access_token",),
        operations={
            "list_teams": VendorOperation("list_teams", "List Teams", "GET", "/team"),
            "list_spaces": VendorOperation(
                "list_spaces", "List Spaces", "GET", "/team/{team_id}/space", ("team_id",),
            ),
            "list_tasks": VendorOperation(
                "list_tasks", "List Tasks", "GET", "/list/{list_id}/task", ("list_id",),
            ),
            "get_task": VendorOperation(
                "get_task", "Get Task", "GET", "/task/{task_id}", ("task_id",),
            ),
            "create_task": VendorOperation(
                "create_task", "Create Task", "POST", "/list/{list_id}/task", ("list_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "update_task": VendorOperation(
                "update_task", "Update Task", "PUT", "/task/{task_id}", ("task_id",),
            ),
            "delete_task": VendorOperation(
                "delete_task", "Delete Task", "DELETE", "/task/{task_id}", ("task_id",),
            ),
        },
    ),
    "clockify": VendorSpec(
        key="clockify",
        display_name="Clockify",
        description="Clockify workspaces, projects, clients, tasks, and time entries.",
        category="productivity",
        base_url="https://api.clockify.me/api/v1",
        auth_kind="header",
        auth_header="X-Api-Key",
        credential_fields=("api_key",),
        operations={
            "list_workspaces": VendorOperation("list_workspaces", "List Workspaces", "GET", "/workspaces"),
            "list_projects": VendorOperation(
                "list_projects", "List Projects", "GET", "/workspaces/{workspace_id}/projects",
                ("workspace_id",),
            ),
            "get_project": VendorOperation(
                "get_project", "Get Project", "GET", "/workspaces/{workspace_id}/projects/{project_id}",
                ("workspace_id", "project_id"),
            ),
            "list_clients": VendorOperation(
                "list_clients", "List Clients", "GET", "/workspaces/{workspace_id}/clients",
                ("workspace_id",),
            ),
            "list_tasks": VendorOperation(
                "list_tasks", "List Tasks", "GET",
                "/workspaces/{workspace_id}/projects/{project_id}/tasks",
                ("workspace_id", "project_id"),
            ),
            "get_time_entry": VendorOperation(
                "get_time_entry", "Get Time Entry", "GET",
                "/workspaces/{workspace_id}/time-entries/{time_entry_id}",
                ("workspace_id", "time_entry_id"),
            ),
            "create_time_entry": VendorOperation(
                "create_time_entry", "Create Time Entry", "POST",
                "/workspaces/{workspace_id}/time-entries", ("workspace_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_time_entry": VendorOperation(
                "delete_time_entry", "Delete Time Entry", "DELETE",
                "/workspaces/{workspace_id}/time-entries/{time_entry_id}",
                ("workspace_id", "time_entry_id"),
            ),
        },
    ),
    "cloudflare": VendorSpec(
        key="cloudflare",
        display_name="Cloudflare",
        description="Cloudflare zones and zone-level authenticated origin pull certificates.",
        category="developer",
        base_url="https://api.cloudflare.com/client/v4",
        auth_kind="bearer",
        credential_fields=("api_token",),
        operations={
            "list_zones": VendorOperation("list_zones", "List Zones", "GET", "/zones"),
            "list_zone_certificates": VendorOperation(
                "list_zone_certificates", "List Zone Certificates", "GET",
                "/zones/{zone_id}/origin_tls_client_auth", ("zone_id",),
            ),
            "get_zone_certificate": VendorOperation(
                "get_zone_certificate", "Get Zone Certificate", "GET",
                "/zones/{zone_id}/origin_tls_client_auth/{certificate_id}",
                ("zone_id", "certificate_id"),
            ),
            "upload_zone_certificate": VendorOperation(
                "upload_zone_certificate", "Upload Zone Certificate", "POST",
                "/zones/{zone_id}/origin_tls_client_auth", ("zone_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_zone_certificate": VendorOperation(
                "delete_zone_certificate", "Delete Zone Certificate", "DELETE",
                "/zones/{zone_id}/origin_tls_client_auth/{certificate_id}",
                ("zone_id", "certificate_id"),
            ),
        },
    ),
    "cockpit": VendorSpec(
        key="cockpit",
        display_name="Cockpit",
        description="Cockpit collections, singletons, and forms on a self-hosted instance.",
        category="marketing",
        base_url="https://{host}/api",
        auth_kind="query",
        query_param="token",
        credential_fields=("token",),
        extra_required=("host",),
        operations={
            "list_collections": VendorOperation(
                "list_collections", "List Collections", "GET", "/collections/listCollections",
            ),
            "get_collection_entries": VendorOperation(
                "get_collection_entries", "Get Collection Entries", "POST",
                "/collections/get/{collection}", ("collection",),
            ),
            "save_collection_entry": VendorOperation(
                "save_collection_entry", "Save Collection Entry", "POST",
                "/collections/save/{collection}", ("collection",),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_singletons": VendorOperation(
                "list_singletons", "List Singletons", "GET", "/singletons/listSingletons",
            ),
            "get_singleton": VendorOperation(
                "get_singleton", "Get Singleton", "GET", "/singletons/get/{singleton}",
                ("singleton",),
            ),
            "submit_form": VendorOperation(
                "submit_form", "Submit Form", "POST", "/forms/submit/{form}", ("form",),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "convert_kit": VendorSpec(
        key="convert_kit",
        display_name="ConvertKit",
        description="ConvertKit forms, tags, custom fields, and sequences.",
        category="marketing",
        base_url="https://api.convertkit.com/v3",
        auth_kind="query",
        query_param="api_secret",
        credential_fields=("api_secret",),
        operations={
            "list_forms": VendorOperation("list_forms", "List Forms", "GET", "/forms"),
            "list_tags": VendorOperation("list_tags", "List Tags", "GET", "/tags"),
            "list_custom_fields": VendorOperation(
                "list_custom_fields", "List Custom Fields", "GET", "/custom_fields",
            ),
            "list_sequences": VendorOperation("list_sequences", "List Sequences", "GET", "/sequences"),
            "subscribe_to_form": VendorOperation(
                "subscribe_to_form", "Subscribe to Form", "POST", "/forms/{form_id}/subscribe",
                ("form_id",), retryable=False, idempotency="non_idempotent",
            ),
            "add_subscriber_to_tag": VendorOperation(
                "add_subscriber_to_tag", "Add Subscriber to Tag", "POST",
                "/tags/{tag_id}/subscribe", ("tag_id",),
                retryable=False, idempotency="non_idempotent",
            ),
        },
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
            "batch": "catalog_conversion_8",
        },
    )


def build_batch8_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Return the batch 8 native connector/definition pairs that can run.

    Unsupported catalog keys are intentionally omitted; see
    :data:`UNSUPPORTED_BATCH8_KEYS` for the per-key reason.
    """
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
