"""Native REST connectors for catalog conversion batch 20.

Each implemented connector uses a fixed vendor host, an explicit auth contract,
and operation paths taken from the corresponding n8n node implementation. Keys
whose n8n node is a local action, a database wire protocol, or requires an
OAuth2 flow the shared :class:`~app.connectors.vendor_rest.VendorRESTConnector`
cannot perform are listed in :data:`UNSUPPORTED_BATCH20_KEYS` with the specific
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


BATCH20_CATALOG_KEYS = frozenset({
    "syncro_msp",
    "tapfiliate",
    "the_hive",
    "the_hive_project",
    "time_saved",
    "timescale_db",
    "totp",
    "twake",
    "twist",
    "twitter",
})

# Alias matching the shorter catalog-batch constant used by earlier batches.
BATCH20_KEYS = BATCH20_CATALOG_KEYS


VENDOR_SPECS: dict[str, VendorSpec] = {
    "syncro_msp": VendorSpec(
        key="syncro_msp",
        display_name="SyncroMSP",
        description=(
            "SyncroMSP contacts, customers, tickets, and RMM alerts. The API key "
            "is sent in the api_key query parameter, matching the SyncroMSP API."
        ),
        category="productivity",
        base_url="https://{subdomain}.syncromsp.com/api/v1",
        auth_kind="query",
        query_param="api_key",
        credential_fields=("api_key",),
        extra_required=("subdomain",),
        operations={
            "list_contacts": VendorOperation(
                "list_contacts", "List Contacts", "GET", "/contacts",
                description=(
                    "List contacts; pass vendor filters such as page, per_page, "
                    "and query as query parameters."
                ),
            ),
            "get_contact": VendorOperation(
                "get_contact", "Get Contact", "GET", "/contacts/{contact_id}",
                ("contact_id",),
            ),
            "create_contact": VendorOperation(
                "create_contact", "Create Contact", "POST", "/contacts", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "update_contact": VendorOperation(
                "update_contact", "Update Contact", "PUT", "/contacts/{contact_id}",
                ("contact_id",),
            ),
            "list_customers": VendorOperation(
                "list_customers", "List Customers", "GET", "/customers",
                description=(
                    "List customers; pass business_name, include_disabled, page, "
                    "and per_page as query parameters."
                ),
            ),
            "get_customer": VendorOperation(
                "get_customer", "Get Customer", "GET", "/customers/{customer_id}",
                ("customer_id",),
            ),
            "create_customer": VendorOperation(
                "create_customer", "Create Customer", "POST", "/customers", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "list_tickets": VendorOperation(
                "list_tickets", "List Tickets", "GET", "/tickets",
                description=(
                    "List tickets; pass vendor filters such as status, customer_id, "
                    "and per_page as query parameters."
                ),
            ),
            "get_ticket": VendorOperation(
                "get_ticket", "Get Ticket", "GET", "/tickets/{ticket_id}",
                ("ticket_id",),
            ),
            "create_ticket": VendorOperation(
                "create_ticket", "Create Ticket", "POST", "/tickets", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "update_ticket": VendorOperation(
                "update_ticket", "Update Ticket", "PUT", "/tickets/{ticket_id}",
                ("ticket_id",),
            ),
            "delete_ticket": VendorOperation(
                "delete_ticket", "Delete Ticket", "DELETE", "/tickets/{ticket_id}",
                ("ticket_id",), idempotency="non_idempotent",
            ),
            "list_rmm_alerts": VendorOperation(
                "list_rmm_alerts", "List RMM Alerts", "GET", "/rmm_alerts",
                description=(
                    "List RMM alerts; pass status (defaults to all in SyncroMSP), "
                    "page, and per_page as query parameters."
                ),
            ),
            "mute_rmm_alert": VendorOperation(
                "mute_rmm_alert", "Mute RMM Alert", "POST",
                "/rmm_alerts/{rmm_alert_id}/mute", ("rmm_alert_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Mute an RMM alert. The body accepts mute_for with the mute "
                    "duration, as required by SyncroMSP."
                ),
            ),
        },
    ),
    "tapfiliate": VendorSpec(
        key="tapfiliate",
        display_name="Tapfiliate",
        description="Tapfiliate affiliates, metadata, and program affiliations.",
        category="marketing",
        base_url="https://api.tapfiliate.com/1.6",
        auth_kind="header",
        auth_header="Api-Key",
        credential_fields=("api_key",),
        operations={
            "create_affiliate": VendorOperation(
                "create_affiliate", "Create Affiliate", "POST", "/affiliates/", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create an affiliate. The body accepts firstname, lastname, "
                    "email, address, and company."
                ),
            ),
            "get_affiliate": VendorOperation(
                "get_affiliate", "Get Affiliate", "GET",
                "/affiliates/{affiliate_id}/", ("affiliate_id",),
            ),
            "list_affiliates": VendorOperation(
                "list_affiliates", "List Affiliates", "GET", "/affiliates/",
                description=(
                    "List affiliates; pass page and vendor filters such as email, "
                    "affiliate_group_id, and referral_code as query parameters."
                ),
            ),
            "delete_affiliate": VendorOperation(
                "delete_affiliate", "Delete Affiliate", "DELETE",
                "/affiliates/{affiliate_id}/", ("affiliate_id",),
                idempotency="non_idempotent",
            ),
            "update_affiliate_metadata": VendorOperation(
                "update_affiliate_metadata", "Update Affiliate Metadata", "PUT",
                "/affiliates/{affiliate_id}/meta-data/", ("affiliate_id",),
                description=(
                    "Replace affiliate metadata with the key/value pairs supplied "
                    "in the request body."
                ),
            ),
            "set_affiliate_metadata": VendorOperation(
                "set_affiliate_metadata", "Set Affiliate Metadata", "PUT",
                "/affiliates/{affiliate_id}/meta-data/{key}/",
                ("affiliate_id", "key"),
                description=(
                    "Set one affiliate metadata key. The body accepts value, matching "
                    "Tapfiliate's meta-data endpoint."
                ),
            ),
            "delete_affiliate_metadata": VendorOperation(
                "delete_affiliate_metadata", "Delete Affiliate Metadata", "DELETE",
                "/affiliates/{affiliate_id}/meta-data/{key}/",
                ("affiliate_id", "key"), idempotency="non_idempotent",
            ),
            "add_program_affiliate": VendorOperation(
                "add_program_affiliate", "Add Program Affiliate", "POST",
                "/programs/{program_id}/affiliates/", ("program_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Add an affiliate to a program. The body accepts affiliate.id "
                    "plus optional program-affiliate fields."
                ),
            ),
            "get_program_affiliate": VendorOperation(
                "get_program_affiliate", "Get Program Affiliate", "GET",
                "/programs/{program_id}/affiliates/{affiliate_id}/",
                ("program_id", "affiliate_id"),
            ),
            "list_program_affiliates": VendorOperation(
                "list_program_affiliates", "List Program Affiliates", "GET",
                "/programs/{program_id}/affiliates/", ("program_id",),
                description=(
                    "List affiliates in a program; pass page and vendor filters as "
                    "query parameters."
                ),
            ),
            "approve_program_affiliate": VendorOperation(
                "approve_program_affiliate", "Approve Program Affiliate", "PUT",
                "/programs/{program_id}/affiliates/{affiliate_id}/approved/",
                ("program_id", "affiliate_id"),
            ),
            "disapprove_program_affiliate": VendorOperation(
                "disapprove_program_affiliate", "Disapprove Program Affiliate",
                "DELETE",
                "/programs/{program_id}/affiliates/{affiliate_id}/approved/",
                ("program_id", "affiliate_id"), idempotency="non_idempotent",
            ),
        },
    ),
    "the_hive": VendorSpec(
        key="the_hive",
        display_name="TheHive",
        description=(
            "TheHive alerts, cases, tasks, observables, and task logs. Search "
            "operations use TheHive 4 query endpoints. Provide the instance "
            "hostname, including a port when it is not 443."
        ),
        category="developer",
        base_url="https://{host}/api",
        auth_kind="bearer",
        credential_fields=("api_key",),
        extra_required=("host",),
        operations={
            "create_alert": VendorOperation(
                "create_alert", "Create Alert", "POST", "/alert", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create an alert. The body accepts title, description, severity, "
                    "date, tags, tlp, status, type, source, sourceRef, and follow."
                ),
            ),
            "get_alert": VendorOperation(
                "get_alert", "Get Alert", "GET", "/alert/{alert_id}",
                ("alert_id",),
                description=(
                    "Get an alert; pass similarity=true as a query parameter to "
                    "include similar alerts."
                ),
            ),
            "search_alerts": VendorOperation(
                "search_alerts", "Search Alerts", "POST", "/alert/_search", (),
                description=(
                    "Search alerts using TheHive's query DSL in the request body. "
                    "Pass range and sort as query parameters."
                ),
            ),
            "create_case": VendorOperation(
                "create_case", "Create Case", "POST", "/case", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a case. The body accepts title, description, severity, "
                    "startDate, owner, flag, tlp, tags, and optional fields."
                ),
            ),
            "get_case": VendorOperation(
                "get_case", "Get Case", "GET", "/case/{case_id}", ("case_id",),
            ),
            "search_cases": VendorOperation(
                "search_cases", "Search Cases", "POST", "/case/_search", (),
                description=(
                    "Search cases using TheHive's query DSL in the request body. "
                    "Pass range and sort as query parameters."
                ),
            ),
            "create_task": VendorOperation(
                "create_task", "Create Task", "POST", "/case/{case_id}/task",
                ("case_id",), retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a task in a case. The body accepts title, status, flag, "
                    "and optional task fields."
                ),
            ),
            "create_observable": VendorOperation(
                "create_observable", "Create Observable", "POST",
                "/case/{case_id}/artifact", ("case_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create an observable in a case. The body accepts dataType, "
                    "message, startDate, tlp, ioc, sighted, status, and data."
                ),
            ),
            "create_log": VendorOperation(
                "create_log", "Create Task Log", "POST",
                "/case/task/{task_id}/log", ("task_id",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a log entry on a task. The body accepts message, "
                    "startDate, and status."
                ),
            ),
        },
    ),
    "the_hive_project": VendorSpec(
        key="the_hive_project",
        display_name="TheHive 5",
        description=(
            "TheHive 5 alerts, cases, tasks, pages, and query API. Provide the "
            "instance hostname, including a port when it is not 443."
        ),
        category="developer",
        base_url="https://{host}/api",
        auth_kind="bearer",
        credential_fields=("api_key",),
        extra_required=("host",),
        operations={
            "create_alert": VendorOperation(
                "create_alert", "Create Alert", "POST", "/v1/alert", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create an alert. The body accepts the alert fields supported by "
                    "TheHive 5, including observables."
                ),
            ),
            "get_alert": VendorOperation(
                "get_alert", "Get Alert", "GET", "/v1/alert/{alert_id}",
                ("alert_id",),
            ),
            "create_case": VendorOperation(
                "create_case", "Create Case", "POST", "/v1/case", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a case with the fields supported by TheHive 5.",
            ),
            "get_case": VendorOperation(
                "get_case", "Get Case", "POST", "/v1/query", (),
                description=(
                    "Get a case through the query API. The body accepts a query "
                    "wrapping getCase with the target case id, as the n8n node does."
                ),
            ),
            "create_task": VendorOperation(
                "create_task", "Create Task", "POST", "/v1/case/{case_id}/task",
                ("case_id",), retryable=False, idempotency="non_idempotent",
                description="Create a task in a case with TheHive 5 task fields.",
            ),
            "create_page": VendorOperation(
                "create_page", "Create Page", "POST", "/v1/case/{case_id}/page",
                ("case_id",), retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a page in a case. The body accepts title, category, and "
                    "content."
                ),
            ),
            "search_cases": VendorOperation(
                "search_cases", "Search Cases", "POST", "/v1/query", (),
                description=(
                    "Search cases through the query API. The body accepts the "
                    "TheHive 5 query DSL, for example listCase with filters and "
                    "pagination."
                ),
            ),
            "execute_query": VendorOperation(
                "execute_query", "Execute Query", "POST", "/v1/query", (),
                description=(
                    "Execute a raw TheHive 5 query. The body accepts query as an "
                    "array of query operations."
                ),
            ),
        },
    ),
    "twake": VendorSpec(
        key="twake",
        display_name="Twake",
        description=(
            "Twake Cloud messages through the n8n Twake plugin endpoint. The "
            "workspace key is sent as a bearer token."
        ),
        category="communication",
        base_url="https://plugins.twake.app/plugins/n8n",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "list_channels": VendorOperation(
                "list_channels", "List Channels", "POST", "/channel", (),
                description=(
                    "List channels available to the workspace key. Twake exposes "
                    "this lookup as a POST with an empty body."
                ),
            ),
            "send_message": VendorOperation(
                "send_message", "Send Message", "POST",
                "/actions/message/save", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send a message. The body must contain an object with "
                    "channel_id, content.formatted, and optional hidden_data."
                ),
            ),
        },
    ),
}


# Keys intentionally left out of build_batch20_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH20_KEYS: dict[str, str] = {
    "time_saved": (
        "n8n's Track Time Saved node is a local workflow action: it validates the "
        "minutesSaved parameter, records the value with this.setMetadata, and "
        "passes the input items through unchanged. It has no vendor host, "
        "credentials, or HTTP endpoint, so VendorRESTConnector cannot perform it."
    ),
    "timescale_db": (
        "n8n's TimescaleDB node opens a PostgreSQL wire-protocol connection with "
        "pg-promise. Its credentials are host, port, database, user, password, and "
        "SSL mode, and its operations execute SQL over TCP. TimescaleDB has no "
        "HTTP REST API for these operations, so VendorRESTConnector cannot run them."
    ),
    "totp": (
        "n8n's TOTP node generates a time-based one-time password locally with the "
        "otpauth library from the secret, label, algorithm, digits, and period in "
        "the totpApi credential. It issues no HTTP request and has no vendor host "
        "or endpoint, so VendorRESTConnector cannot generate the token."
    ),
    "twist": (
        "n8n's Twist node calls https://api.twist.com/api/v3 through requestOAuth2 "
        "with the twistOAuth2Api credential, which requires an OAuth2 "
        "authorization-code flow and token refresh. VendorRESTConnector only "
        "supports static credentials and has no OAuth2 exchange or refresh, so "
        "Twist channels, threads, comments, and messages cannot authenticate."
    ),
    "twitter": (
        "n8n's X (Twitter) node calls https://api.x.com/2 through requestOAuth2 "
        "with the twitterOAuth2Api credential, which requires an OAuth2 "
        "authorization-code flow (with PKCE) and token refresh. VendorRESTConnector "
        "only supports static credentials and has no OAuth2 exchange or refresh, so "
        "tweets, users, lists, and direct messages cannot authenticate."
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
                validation_schema={
                    "type": "object",
                    "properties": credential_properties,
                },
                encryption_required=True,
            )
        },
        metadata={
            "implementation": "native",
            "batch": "catalog_conversion_20",
        },
    )


def build_batch20_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 20 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
