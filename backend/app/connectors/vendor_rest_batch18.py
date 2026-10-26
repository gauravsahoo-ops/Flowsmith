"""Native REST connectors for catalog conversion batch 18.

Each connector uses a fixed vendor host, an explicit auth contract, and
operation paths taken from the corresponding n8n node implementation. Keys
whose n8n node is a local transform, a test-only simulation node, or a
protocol the shared :class:`~app.connectors.vendor_rest.VendorRESTConnector`
cannot authenticate or encode are listed in
:data:`UNSUPPORTED_BATCH18_KEYS` with the specific reason instead of being
given invented endpoints.
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


BATCH18_CATALOG_KEYS = frozenset({
    "security_scorecard",
    "segment",
    "send_grid",
    "sendy",
    "sentry_io",
    "service_now",
    "set",
    "signl4",
    "simulate",
    "sort",
})

# Alias matching the shorter catalog-batch constant used by earlier batches.
BATCH18_KEYS = BATCH18_CATALOG_KEYS


VENDOR_SPECS: dict[str, VendorSpec] = {
    "security_scorecard": VendorSpec(
        key="security_scorecard",
        display_name="SecurityScorecard",
        description=(
            "SecurityScorecard company scores, factor history, industry scores, "
            "portfolios, invitations, and reports."
        ),
        category="security",
        base_url="https://api.securityscorecard.io",
        auth_kind="header",
        auth_header="Authorization",
        auth_prefix="Token ",
        credential_fields=("api_key",),
        operations={
            "get_company_scorecard": VendorOperation(
                "get_company_scorecard", "Get Company Scorecard", "GET",
                "/companies/{scorecard_identifier}", ("scorecard_identifier",),
                description=(
                    "Get a company's information and scorecard. The identifier can "
                    "be a domain, company name, or scorecard identifier."
                ),
            ),
            "get_company_factors": VendorOperation(
                "get_company_factors", "Get Company Factor Scores", "GET",
                "/companies/{scorecard_identifier}/factors", ("scorecard_identifier",),
                description="Get company factor scores; pass filters as query parameters.",
            ),
            "get_company_factor_history": VendorOperation(
                "get_company_factor_history", "Get Company Historical Factor Scores", "GET",
                "/companies/{scorecard_identifier}/history/factors/score",
                ("scorecard_identifier",),
                description=(
                    "Get historical factor scores; pass date_from, date_to, timing, "
                    "and other options as query parameters."
                ),
            ),
            "get_company_score_plan": VendorOperation(
                "get_company_score_plan", "Get Company Score Plan", "GET",
                "/companies/{scorecard_identifier}/score-plans/by-target/{target_score}",
                ("scorecard_identifier", "target_score"),
            ),
            "get_industry_score": VendorOperation(
                "get_industry_score", "Get Industry Score", "GET",
                "/industries/{industry}/score", ("industry",),
            ),
            "get_industry_factors": VendorOperation(
                "get_industry_factors", "Get Industry Factor Scores", "GET",
                "/industries/{industry}/history/factors", ("industry",),
                description=(
                    "Get industry factor history; pass from, to, and timing as query "
                    "parameters."
                ),
            ),
            "list_portfolios": VendorOperation(
                "list_portfolios", "List Portfolios", "GET", "/portfolios",
            ),
            "create_portfolio": VendorOperation(
                "create_portfolio", "Create Portfolio", "POST", "/portfolios", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "update_portfolio": VendorOperation(
                "update_portfolio", "Update Portfolio", "PUT", "/portfolios/{portfolio_id}",
                ("portfolio_id",),
            ),
            "delete_portfolio": VendorOperation(
                "delete_portfolio", "Delete Portfolio", "DELETE",
                "/portfolios/{portfolio_id}", ("portfolio_id",),
            ),
            "list_portfolio_companies": VendorOperation(
                "list_portfolio_companies", "List Portfolio Companies", "GET",
                "/portfolios/{portfolio_id}/companies", ("portfolio_id",),
                description=(
                    "List portfolio companies; pass grade, industry, issue_type, "
                    "status, and vulnerability as query parameters."
                ),
            ),
            "add_portfolio_company": VendorOperation(
                "add_portfolio_company", "Add Portfolio Company", "PUT",
                "/portfolios/{portfolio_id}/companies/{domain}",
                ("portfolio_id", "domain"),
            ),
            "remove_portfolio_company": VendorOperation(
                "remove_portfolio_company", "Remove Portfolio Company", "DELETE",
                "/portfolios/{portfolio_id}/companies/{domain}",
                ("portfolio_id", "domain"),
            ),
            "create_invitation": VendorOperation(
                "create_invitation", "Create Invitation", "POST", "/invitations", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Invite a user. The body accepts email, first_name, last_name, "
                    "message, and the vendor's additional invitation fields."
                ),
            ),
            "generate_report": VendorOperation(
                "generate_report", "Generate Report", "POST", "/reports/{report_type}",
                ("report_type",), retryable=False, idempotency="non_idempotent",
                description=(
                    "Generate a report such as detailed, summary, issues, portfolio, "
                    "or full-scorecard-json. Send the report options in the body."
                ),
            ),
            "list_recent_reports": VendorOperation(
                "list_recent_reports", "List Recent Reports", "GET", "/reports/recent",
            ),
        },
    ),
    "segment": VendorSpec(
        key="segment",
        display_name="Segment",
        description=(
            "Segment HTTP Tracking API identify, group, track, and page calls, "
            "authenticated with the source write key."
        ),
        category="analytics",
        base_url="https://api.segment.io/v1",
        auth_kind="basic",
        basic_user_field="api_key",
        credential_fields=("api_key",),
        operations={
            "identify": VendorOperation(
                "identify", "Identify User", "POST", "/identify", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Identify a user. The body accepts userId, anonymousId, traits, "
                    "context, and integrations."
                ),
            ),
            "group": VendorOperation(
                "group", "Associate User With Group", "POST", "/group", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Associate a user with a group. The body accepts userId, "
                    "anonymousId, groupId, traits, context, and integrations."
                ),
            ),
            "track": VendorOperation(
                "track", "Track Event", "POST", "/track", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Record an event. The body accepts userId, anonymousId, event, "
                    "properties, context, and integrations."
                ),
            ),
            "page": VendorOperation(
                "page", "Page View", "POST", "/page", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Record a page view. The body accepts userId, anonymousId, name, "
                    "properties, context, and integrations."
                ),
            ),
        },
    ),
    "send_grid": VendorSpec(
        key="send_grid",
        display_name="SendGrid",
        description="SendGrid marketing contacts and lists, plus transactional mail.",
        category="communication",
        base_url="https://api.sendgrid.com/v3",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "list_contacts": VendorOperation(
                "list_contacts", "List Contacts", "GET", "/marketing/contacts",
            ),
            "search_contacts": VendorOperation(
                "search_contacts", "Search Contacts", "POST", "/marketing/contacts/search",
                description=(
                    "Search contacts with an SGQL query. The body accepts query and "
                    "possibly page_size."
                ),
            ),
            "get_contact": VendorOperation(
                "get_contact", "Get Contact", "GET", "/marketing/contacts/{contact_id}",
                ("contact_id",),
            ),
            "upsert_contacts": VendorOperation(
                "upsert_contacts", "Upsert Contacts", "PUT", "/marketing/contacts",
                description=(
                    "Create or update contacts. The body accepts contacts and "
                    "list_ids."
                ),
            ),
            "list_lists": VendorOperation(
                "list_lists", "List Lists", "GET", "/marketing/lists",
            ),
            "get_list": VendorOperation(
                "get_list", "Get List", "GET", "/marketing/lists/{list_id}", ("list_id",),
                description="Get a list; pass contact_sample as a query parameter.",
            ),
            "create_list": VendorOperation(
                "create_list", "Create List", "POST", "/marketing/lists", (),
                retryable=False, idempotency="non_idempotent",
                description="Create a marketing list with a name in the body.",
            ),
            "update_list": VendorOperation(
                "update_list", "Update List", "PATCH", "/marketing/lists/{list_id}",
                ("list_id",), description="Rename a marketing list with a name in the body.",
            ),
            "send_mail": VendorOperation(
                "send_mail", "Send Mail", "POST", "/mail/send", (),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Send a transactional email using SendGrid's v3 mail body, "
                    "including personalizations and content."
                ),
            ),
        },
    ),
    "sentry_io": VendorSpec(
        key="sentry_io",
        display_name="Sentry.io",
        description=(
            "Sentry.io organizations, projects, events, issues, releases, and teams "
            "using a Sentry access token."
        ),
        category="developer",
        base_url="https://sentry.io",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_organizations": VendorOperation(
                "list_organizations", "List Organizations", "GET", "/api/0/organizations/",
                description="List organizations; pass member, owner, and limit as query parameters.",
            ),
            "get_organization": VendorOperation(
                "get_organization", "Get Organization", "GET",
                "/api/0/organizations/{organization_slug}/", ("organization_slug",),
            ),
            "create_organization": VendorOperation(
                "create_organization", "Create Organization", "POST", "/api/0/organizations/",
                (), retryable=False, idempotency="non_idempotent",
                description=(
                    "Create an organization. The body accepts name, agreeTerms, and "
                    "optionally slug."
                ),
            ),
            "update_organization": VendorOperation(
                "update_organization", "Update Organization", "PUT",
                "/api/0/organizations/{organization_slug}/", ("organization_slug",),
            ),
            "list_projects": VendorOperation(
                "list_projects", "List Projects", "GET", "/api/0/projects/",
            ),
            "create_project": VendorOperation(
                "create_project", "Create Project", "POST",
                "/api/0/teams/{organization_slug}/{team_slug}/projects/",
                ("organization_slug", "team_slug"),
                retryable=False, idempotency="non_idempotent",
                description="Create a project in a team with a name and optional fields in the body.",
            ),
            "get_project": VendorOperation(
                "get_project", "Get Project", "GET",
                "/api/0/projects/{organization_slug}/{project_slug}/",
                ("organization_slug", "project_slug"),
            ),
            "update_project": VendorOperation(
                "update_project", "Update Project", "PUT",
                "/api/0/projects/{organization_slug}/{project_slug}/",
                ("organization_slug", "project_slug"),
            ),
            "delete_project": VendorOperation(
                "delete_project", "Delete Project", "DELETE",
                "/api/0/projects/{organization_slug}/{project_slug}/",
                ("organization_slug", "project_slug"),
            ),
            "list_events": VendorOperation(
                "list_events", "List Events", "GET",
                "/api/0/projects/{organization_slug}/{project_slug}/events/",
                ("organization_slug", "project_slug"),
                description="List project events; pass full, limit, and cursor as query parameters.",
            ),
            "get_event": VendorOperation(
                "get_event", "Get Event", "GET",
                "/api/0/projects/{organization_slug}/{project_slug}/events/{event_id}/",
                ("organization_slug", "project_slug", "event_id"),
            ),
            "list_issues": VendorOperation(
                "list_issues", "List Issues", "GET",
                "/api/0/projects/{organization_slug}/{project_slug}/issues/",
                ("organization_slug", "project_slug"),
                description="List project issues; pass query, statsPeriod, and limit as query parameters.",
            ),
            "get_issue": VendorOperation(
                "get_issue", "Get Issue", "GET", "/api/0/issues/{issue_id}/", ("issue_id",),
            ),
            "update_issue": VendorOperation(
                "update_issue", "Update Issue", "PUT", "/api/0/issues/{issue_id}/", ("issue_id",),
                description=(
                    "Update an issue. The body accepts status, assignedTo, hasSeen, "
                    "isBookmarked, isSubscribed, and isPublic."
                ),
            ),
            "delete_issue": VendorOperation(
                "delete_issue", "Delete Issue", "DELETE", "/api/0/issues/{issue_id}/",
                ("issue_id",),
            ),
            "list_releases": VendorOperation(
                "list_releases", "List Releases", "GET",
                "/api/0/organizations/{organization_slug}/releases/", ("organization_slug",),
                description="List releases; pass query and limit as query parameters.",
            ),
            "get_release": VendorOperation(
                "get_release", "Get Release", "GET",
                "/api/0/organizations/{organization_slug}/releases/{version}/",
                ("organization_slug", "version"),
            ),
            "create_release": VendorOperation(
                "create_release", "Create Release", "POST",
                "/api/0/organizations/{organization_slug}/releases/", ("organization_slug",),
                retryable=False, idempotency="non_idempotent",
                description=(
                    "Create a release. The body accepts version, url, projects, "
                    "dateReleased, commits, and refs."
                ),
            ),
            "update_release": VendorOperation(
                "update_release", "Update Release", "PUT",
                "/api/0/organizations/{organization_slug}/releases/{version}/",
                ("organization_slug", "version"),
            ),
            "delete_release": VendorOperation(
                "delete_release", "Delete Release", "DELETE",
                "/api/0/organizations/{organization_slug}/releases/{version}/",
                ("organization_slug", "version"),
            ),
            "list_teams": VendorOperation(
                "list_teams", "List Teams", "GET",
                "/api/0/organizations/{organization_slug}/teams/", ("organization_slug",),
            ),
            "get_team": VendorOperation(
                "get_team", "Get Team", "GET",
                "/api/0/teams/{organization_slug}/{team_slug}/",
                ("organization_slug", "team_slug"),
            ),
            "create_team": VendorOperation(
                "create_team", "Create Team", "POST",
                "/api/0/organizations/{organization_slug}/teams/", ("organization_slug",),
                retryable=False, idempotency="non_idempotent",
                description="Create a team with a name and optional slug in the body.",
            ),
            "update_team": VendorOperation(
                "update_team", "Update Team", "PUT",
                "/api/0/teams/{organization_slug}/{team_slug}/",
                ("organization_slug", "team_slug"),
            ),
            "delete_team": VendorOperation(
                "delete_team", "Delete Team", "DELETE",
                "/api/0/teams/{organization_slug}/{team_slug}/",
                ("organization_slug", "team_slug"),
            ),
        },
    ),
    "service_now": VendorSpec(
        key="service_now",
        display_name="ServiceNow",
        description=(
            "ServiceNow incidents and arbitrary table records on a self-hosted "
            "instance. Provide the instance subdomain."
        ),
        category="productivity",
        base_url="https://{subdomain}.service-now.com/api",
        auth_kind="basic",
        basic_user_field="username",
        basic_password_field="password",
        credential_fields=("username", "password"),
        extra_required=("subdomain",),
        operations={
            "create_incident": VendorOperation(
                "create_incident", "Create Incident", "POST", "/now/table/incident", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "get_incident": VendorOperation(
                "get_incident", "Get Incident", "GET", "/now/table/incident/{incident_id}",
                ("incident_id",),
                description="Get an incident; pass sysparm_fields and sysparm_display_value as query parameters.",
            ),
            "list_incidents": VendorOperation(
                "list_incidents", "List Incidents", "GET", "/now/table/incident",
                description="List incidents; pass sysparm_query, sysparm_fields, and sysparm_limit as query parameters.",
            ),
            "update_incident": VendorOperation(
                "update_incident", "Update Incident", "PATCH",
                "/now/table/incident/{incident_id}", ("incident_id",),
                description="Update incident fields with a JSON body.",
            ),
            "delete_incident": VendorOperation(
                "delete_incident", "Delete Incident", "DELETE",
                "/now/table/incident/{incident_id}", ("incident_id",),
            ),
            "create_table_record": VendorOperation(
                "create_table_record", "Create Table Record", "POST",
                "/now/table/{table_name}", ("table_name",),
                retryable=False, idempotency="non_idempotent",
                description="Create a record in any table using a JSON body of column values.",
            ),
            "get_table_record": VendorOperation(
                "get_table_record", "Get Table Record", "GET",
                "/now/table/{table_name}/{record_id}", ("table_name", "record_id"),
            ),
            "list_table_records": VendorOperation(
                "list_table_records", "List Table Records", "GET",
                "/now/table/{table_name}", ("table_name",),
                description="List rows from a table; pass sysparm_query and sysparm_limit as query parameters.",
            ),
            "update_table_record": VendorOperation(
                "update_table_record", "Update Table Record", "PATCH",
                "/now/table/{table_name}/{record_id}", ("table_name", "record_id"),
            ),
            "delete_table_record": VendorOperation(
                "delete_table_record", "Delete Table Record", "DELETE",
                "/now/table/{table_name}/{record_id}", ("table_name", "record_id"),
            ),
        },
    ),
}


# Keys intentionally left out of build_batch18_connectors(). Keeping the reasons
# next to the spec table makes each gap explicit instead of publishing a
# connector whose operations cannot authenticate or have no REST host at all.
UNSUPPORTED_BATCH18_KEYS: dict[str, str] = {
    "sendy": (
        "n8n's Sendy node takes the installation URL from the sendyApi credential "
        "instead of a fixed vendor host, appends the API key to every "
        "form-urlencoded request body as api_key, and sends requests with "
        "Content-Type: application/x-www-form-urlencoded. VendorRESTConnector "
        "requires a fixed host and sends JSON bodies without injecting credentials "
        "into them, so Sendy requests would be unauthenticated and mis-encoded."
    ),
    "set": (
        "n8n's Set node is a local transform that adds, edits, or removes fields on "
        "input items in memory. It has no vendor host, credential, or REST endpoint, "
        "so there is nothing for a VendorRESTConnector to call."
    ),
    "signl4": (
        "n8n's SIGNL4 node puts the team secret directly in the webhook path "
        "(https://connect.signl4.com/webhook/{teamSecret}), sends alert metadata as "
        "X-S4-* form fields, and can attach binary files as multipart form data. "
        "VendorRESTConnector cannot build multipart bodies or set per-operation "
        "form fields, so it cannot encode SIGNL4 alerts or resolutions."
    ),
    "simulate": (
        "n8n's Simulate node is a hidden local test utility that returns or slices "
        "its input items, optionally emitting custom JSON and delaying execution. It has "
        "no vendor host, credential, or REST endpoint, so there is nothing for a "
        "VendorRESTConnector to call."
    ),
    "sort": (
        "n8n's Sort node is a local transform that reorders input items by field, "
        "random order, or custom code. It has no vendor host, credential, or REST "
        "endpoint, so there is nothing for a VendorRESTConnector to call."
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
            "batch": "catalog_conversion_18",
        },
    )


def build_batch18_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    """Build the batch 18 connector instances and their definitions."""
    return [
        (VendorRESTConnector(spec), _build_definition(spec))
        for spec in VENDOR_SPECS.values()
    ]
