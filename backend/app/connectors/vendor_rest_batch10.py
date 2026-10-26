"""Native REST connectors for catalog conversion batch 10.

Each implemented connector uses a fixed vendor host or tenant host plus the
auth contract and operation paths taken from the matching n8n node. Catalog
keys that are local transforms, use a non-HTTP protocol, or depend on OAuth2
authorization-code/refresh flows are listed in ``UNSUPPORTED_BATCH10_KEYS``
with the reason they were not converted. No placeholders are invented for
those keys.
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


BATCH10_KEYS = frozenset({
    "invoice_ninja",
    "iterable",
    "jenkins",
    "jina_ai",
    "jwt",
    "keap",
    "ko_bo_toolbox",
    "ldap",
    "limit",
    "line",
})


UNSUPPORTED_BATCH10_KEYS: dict[str, str] = {
    "jwt": (
        "n8n's JWT node signs, decodes, and verifies JSON Web Tokens locally with "
        "the jsonwebtoken library. It has no vendor REST host, base URL, or HTTP "
        "operations, so it cannot be represented as a VendorRESTConnector."
    ),
    "keap": (
        "n8n authenticates Keap with the keapOAuth2Api credential and calls "
        "requestOAuth2 for every operation; VendorRESTConnector has no OAuth2 "
        "authorization-code grant or token-refresh handling. A static bearer token "
        "would expire and cannot be refreshed by this connector family."
    ),
    "ldap": (
        "n8n's LDAP node speaks the LDAP protocol over TCP (bind, search, compare, "
        "add, delete, modify, and rename) through the ldapts client. It has no HTTP "
        "REST API, so VendorRESTConnector cannot implement it."
    ),
    "limit": (
        "n8n's Limit node is a local flow-control transform that slices the input "
        "items array. It has no vendor host, credentials, or HTTP operations."
    ),
    "line": (
        "n8n's Line node uses the lineNotifyOAuth2Api OAuth2 credential and posts "
        "multipart/form-data to notify-api.line.me. VendorRESTConnector has no OAuth2 "
        "flow and only sends JSON bodies. LINE Notify was also discontinued on "
        "April 1, 2025, so the endpoint no longer sends notifications."
    ),
}


VENDOR_SPECS: dict[str, VendorSpec] = {
    "invoice_ninja": VendorSpec(
        key="invoice_ninja",
        display_name="Invoice Ninja",
        description=(
            "Invoice Ninja v5 clients, invoices, tasks, payments, expenses, quotes, "
            "and bank transactions. Uses the hosted v5 API; the API token is supplied "
            "in the api_key credential field."
        ),
        category="finance",
        base_url="https://invoicing.co/api/v1",
        auth_kind="header",
        auth_header="X-API-TOKEN",
        credential_fields=("api_key",),
        operations={
            "list_clients": VendorOperation(
                "list_clients", "List Clients", "GET", "/clients",
                description="List clients; filters and pagination go in payload.params.",
            ),
            "get_client": VendorOperation(
                "get_client", "Get Client", "GET", "/clients/{client_id}", ("client_id",),
            ),
            "create_client": VendorOperation(
                "create_client", "Create Client", "POST", "/clients", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_client": VendorOperation(
                "delete_client", "Delete Client", "DELETE", "/clients/{client_id}", ("client_id",),
            ),
            "list_invoices": VendorOperation(
                "list_invoices", "List Invoices", "GET", "/invoices",
                description="List invoices; filters and pagination go in payload.params.",
            ),
            "get_invoice": VendorOperation(
                "get_invoice", "Get Invoice", "GET", "/invoices/{invoice_id}", ("invoice_id",),
            ),
            "create_invoice": VendorOperation(
                "create_invoice", "Create Invoice", "POST", "/invoices", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_invoice": VendorOperation(
                "delete_invoice", "Delete Invoice", "DELETE", "/invoices/{invoice_id}", ("invoice_id",),
            ),
            "email_invoice": VendorOperation(
                "email_invoice", "Email Invoice", "GET", "/invoices/{invoice_id}/email",
                ("invoice_id",), retryable=False, idempotency="non_idempotent",
            ),
            "list_tasks": VendorOperation("list_tasks", "List Tasks", "GET", "/tasks"),
            "get_task": VendorOperation(
                "get_task", "Get Task", "GET", "/tasks/{task_id}", ("task_id",),
            ),
            "create_task": VendorOperation(
                "create_task", "Create Task", "POST", "/tasks", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_task": VendorOperation(
                "delete_task", "Delete Task", "DELETE", "/tasks/{task_id}", ("task_id",),
            ),
            "list_payments": VendorOperation("list_payments", "List Payments", "GET", "/payments"),
            "get_payment": VendorOperation(
                "get_payment", "Get Payment", "GET", "/payments/{payment_id}", ("payment_id",),
            ),
            "create_payment": VendorOperation(
                "create_payment", "Create Payment", "POST", "/payments", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_payment": VendorOperation(
                "delete_payment", "Delete Payment", "DELETE", "/payments/{payment_id}", ("payment_id",),
            ),
            "list_expenses": VendorOperation("list_expenses", "List Expenses", "GET", "/expenses"),
            "get_expense": VendorOperation(
                "get_expense", "Get Expense", "GET", "/expenses/{expense_id}", ("expense_id",),
            ),
            "create_expense": VendorOperation(
                "create_expense", "Create Expense", "POST", "/expenses", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_expense": VendorOperation(
                "delete_expense", "Delete Expense", "DELETE", "/expenses/{expense_id}", ("expense_id",),
            ),
            "list_quotes": VendorOperation("list_quotes", "List Quotes", "GET", "/quotes"),
            "get_quote": VendorOperation(
                "get_quote", "Get Quote", "GET", "/quotes/{quote_id}", ("quote_id",),
            ),
            "create_quote": VendorOperation(
                "create_quote", "Create Quote", "POST", "/quotes", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_quote": VendorOperation(
                "delete_quote", "Delete Quote", "DELETE", "/quotes/{quote_id}", ("quote_id",),
            ),
            "email_quote": VendorOperation(
                "email_quote", "Email Quote", "GET", "/quotes/{quote_id}/email",
                ("quote_id",), retryable=False, idempotency="non_idempotent",
            ),
            "list_bank_transactions": VendorOperation(
                "list_bank_transactions", "List Bank Transactions", "GET", "/bank_transactions",
            ),
            "get_bank_transaction": VendorOperation(
                "get_bank_transaction", "Get Bank Transaction", "GET",
                "/bank_transactions/{bank_transaction_id}", ("bank_transaction_id",),
            ),
            "create_bank_transaction": VendorOperation(
                "create_bank_transaction", "Create Bank Transaction", "POST",
                "/bank_transactions", (), retryable=False, idempotency="non_idempotent",
            ),
            "delete_bank_transaction": VendorOperation(
                "delete_bank_transaction", "Delete Bank Transaction", "DELETE",
                "/bank_transactions/{bank_transaction_id}", ("bank_transaction_id",),
            ),
            "match_bank_transaction": VendorOperation(
                "match_bank_transaction", "Match Bank Transaction", "POST",
                "/bank_transactions/match", (), retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "iterable": VendorSpec(
        key="iterable",
        display_name="Iterable",
        description="Iterable events, user profiles, and user lists on the US data center.",
        category="marketing",
        base_url="https://api.iterable.com/api",
        auth_kind="header",
        auth_header="Api_Key",
        credential_fields=("api_key",),
        operations={
            "track_events": VendorOperation(
                "track_events", "Track Events", "POST", "/events/trackBulk", (),
                retryable=False, idempotency="non_idempotent",
                description="Track a batch of events; body is {\"events\": [...]}.",
            ),
            "upsert_user": VendorOperation(
                "upsert_user", "Create or Update User", "POST", "/users/update", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "delete_user": VendorOperation(
                "delete_user", "Delete User by Email", "DELETE", "/users/{email}", ("email",),
            ),
            "delete_user_by_user_id": VendorOperation(
                "delete_user_by_user_id", "Delete User by User ID", "DELETE",
                "/users/byUserId/{user_id}", ("user_id",),
            ),
            "get_user": VendorOperation(
                "get_user", "Get User by Email", "GET", "/users/getByEmail", ("email",),
                description="Pass email in payload.params so it is sent as a query parameter.",
            ),
            "get_user_by_user_id": VendorOperation(
                "get_user_by_user_id", "Get User by User ID", "GET",
                "/users/byUserId/{user_id}", ("user_id",),
            ),
            "add_users_to_list": VendorOperation(
                "add_users_to_list", "Add Users to List", "POST", "/lists/subscribe", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "remove_users_from_list": VendorOperation(
                "remove_users_from_list", "Remove Users from List", "POST",
                "/lists/unsubscribe", (), retryable=False, idempotency="non_idempotent",
            ),
            "list_lists": VendorOperation("list_lists", "List Lists", "GET", "/lists"),
        },
    ),
    "jenkins": VendorSpec(
        key="jenkins",
        display_name="Jenkins",
        description=(
            "Jenkins jobs, builds, and instance controls on a self-hosted server. "
            "Supply the host without a scheme in the host parameter; credentials use "
            "the Jenkins username and API token. XML job creation and form-encoded "
            "parameterized builds are not supported by this JSON-only connector."
        ),
        category="developer",
        base_url="https://{host}",
        auth_kind="basic",
        basic_user_field="username",
        basic_password_field="api_key",
        credential_fields=("username", "api_key"),
        extra_required=("host",),
        operations={
            "get_instance": VendorOperation("get_instance", "Get Instance", "GET", "/api/json"),
            "trigger_job": VendorOperation(
                "trigger_job", "Trigger Job", "POST", "/job/{job_name}/build", ("job_name",),
                retryable=False, idempotency="non_idempotent",
            ),
            "copy_job": VendorOperation(
                "copy_job", "Copy Job", "POST",
                "/createItem?name={new_job}&mode=copy&from={job_name}",
                ("new_job", "job_name"), retryable=False, idempotency="non_idempotent",
            ),
            "list_builds": VendorOperation(
                "list_builds", "List Builds", "GET", "/job/{job_name}/api/json?tree=builds[*]",
                ("job_name",),
            ),
            "quiet_down": VendorOperation(
                "quiet_down", "Quiet Down", "POST", "/quietDown", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "cancel_quiet_down": VendorOperation(
                "cancel_quiet_down", "Cancel Quiet Down", "POST", "/cancelQuietDown", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "safe_restart": VendorOperation(
                "safe_restart", "Safely Restart", "POST", "/safeRestart", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "shutdown": VendorOperation(
                "shutdown", "Shutdown", "POST", "/exit", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "safe_shutdown": VendorOperation(
                "safe_shutdown", "Safely Shutdown", "POST", "/safeExit", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "jina_ai": VendorSpec(
        key="jina_ai",
        display_name="Jina AI",
        description=(
            "Jina AI Reader converts a URL into LLM-friendly content. The search and "
            "deep-research operations use separate fixed hosts (s.jina.ai and "
            "deepsearch.jina.ai) and are not exposed by this single-host connector."
        ),
        category="ai",
        base_url="https://r.jina.ai",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "read": VendorOperation(
                "read", "Read URL Content", "GET", "/{url}", ("url",),
                description=(
                    "Fetch a URL and return clean content. Pass the full source URL as "
                    "the url parameter; optional Jina reader headers are not exposed."
                ),
            ),
        },
    ),
    "ko_bo_toolbox": VendorSpec(
        key="ko_bo_toolbox",
        display_name="KoBoToolbox",
        description=(
            "KoBoToolbox forms, submissions, hooks, and files on a self-hosted or "
            "kf.kobotoolbox.org server. Supply the host without a scheme in the host "
            "parameter; the API token is supplied in the api_key credential field."
        ),
        category="productivity",
        base_url="https://{host}",
        auth_kind="header",
        auth_header="Authorization",
        auth_prefix="Token ",
        credential_fields=("api_key",),
        extra_required=("host",),
        operations={
            "list_forms": VendorOperation(
                "list_forms", "List Forms", "GET", "/api/v2/assets/",
                description="List assets; pass q=asset_type:survey to list survey forms.",
            ),
            "get_form": VendorOperation(
                "get_form", "Get Form", "GET", "/api/v2/assets/{form_id}", ("form_id",),
            ),
            "redeploy_form": VendorOperation(
                "redeploy_form", "Redeploy Form", "PATCH",
                "/api/v2/assets/{form_id}/deployment/", ("form_id",),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_submissions": VendorOperation(
                "list_submissions", "List Submissions", "GET",
                "/api/v2/assets/{form_id}/data/", ("form_id",),
            ),
            "get_submission": VendorOperation(
                "get_submission", "Get Submission", "GET",
                "/api/v2/assets/{form_id}/data/{submission_id}",
                ("form_id", "submission_id"),
            ),
            "delete_submission": VendorOperation(
                "delete_submission", "Delete Submission", "DELETE",
                "/api/v2/assets/{form_id}/data/{submission_id}",
                ("form_id", "submission_id"),
            ),
            "get_validation_status": VendorOperation(
                "get_validation_status", "Get Validation Status", "GET",
                "/api/v2/assets/{form_id}/data/{submission_id}/validation_status/",
                ("form_id", "submission_id"),
            ),
            "set_validation_status": VendorOperation(
                "set_validation_status", "Set Validation Status", "PATCH",
                "/api/v2/assets/{form_id}/data/{submission_id}/validation_status/",
                ("form_id", "submission_id"),
                retryable=False, idempotency="non_idempotent",
                description="Body is {\"validation_status.uid\": \"<status>\"}.",
            ),
            "list_hooks": VendorOperation(
                "list_hooks", "List Hooks", "GET",
                "/api/v2/assets/{form_id}/hooks/", ("form_id",),
            ),
            "get_hook": VendorOperation(
                "get_hook", "Get Hook", "GET",
                "/api/v2/assets/{form_id}/hooks/{hook_id}", ("form_id", "hook_id"),
            ),
            "retry_hook": VendorOperation(
                "retry_hook", "Retry Hook", "PATCH",
                "/api/v2/assets/{form_id}/hooks/{hook_id}/retry/",
                ("form_id", "hook_id"),
                retryable=False, idempotency="non_idempotent",
            ),
            "get_hook_logs": VendorOperation(
                "get_hook_logs", "Get Hook Logs", "GET",
                "/api/v2/assets/{form_id}/hooks/{hook_id}/logs/",
                ("form_id", "hook_id"),
            ),
            "retry_hook_log": VendorOperation(
                "retry_hook_log", "Retry Hook Log", "PATCH",
                "/api/v2/assets/{form_id}/hooks/{hook_id}/logs/{log_id}/retry/",
                ("form_id", "hook_id", "log_id"),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_files": VendorOperation(
                "list_files", "List Files", "GET",
                "/api/v2/assets/{form_id}/files", ("form_id",),
                description="List form media files; pass file_type=form_media in payload.params.",
            ),
            "get_file": VendorOperation(
                "get_file", "Get File", "GET",
                "/api/v2/assets/{form_id}/files/{file_id}", ("form_id", "file_id"),
            ),
            "delete_file": VendorOperation(
                "delete_file", "Delete File", "DELETE",
                "/api/v2/assets/{form_id}/files/{file_id}", ("form_id", "file_id"),
            ),
            "create_file": VendorOperation(
                "create_file", "Create File", "POST",
                "/api/v2/assets/{form_id}/files/", ("form_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Body carries description, file_type, metadata, and either "
                    "base64Encoded or a redirect_url in metadata."
                ),
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
            "batch": "catalog_conversion_10",
        },
    )


def build_batch10_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 10 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
