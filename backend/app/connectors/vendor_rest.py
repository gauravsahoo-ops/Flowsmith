"""Native REST connector family for the first catalog conversion batch.

These are vendor-specific connectors with fixed hosts, auth handling, and
operation maps. They are intentionally small first-class connectors, not
catalog-only adapters that accept an arbitrary endpoint_url.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorSDK,
    CredentialTypeV1,
    make_connector_error,
)


@dataclass(frozen=True)
class VendorOperation:
    key: str
    display_name: str
    method: str
    path: str
    requires: tuple[str, ...] = ()
    retryable: bool = True
    idempotency: str = "idempotent"
    description: str = ""


@dataclass(frozen=True)
class VendorSpec:
    key: str
    display_name: str
    description: str
    category: str
    base_url: str
    auth_kind: str  # bearer | basic | header
    credential_fields: tuple[str, ...]
    operations: dict[str, VendorOperation]
    auth_header: str = ""
    auth_prefix: str = ""
    query_param: str = ""
    basic_user_field: str = ""
    basic_user_literal: str = ""
    basic_password_field: str = ""
    default_password: str = ""
    extra_required: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


BATCH1_KEYS = frozenset({
    "action_network", "bamboo_hr", "chargebee", "circle_ci", "confluence",
    "contentful", "customer_io", "databricks", "freshservice", "bitly",
})

VENDOR_SPECS: dict[str, VendorSpec] = {
    "action_network": VendorSpec(
        key="action_network",
        display_name="Action Network",
        description="Action Network people, events, and advocacy actions.",
        category="crm",
        base_url="https://actionnetwork.org/api/v2",
        auth_kind="header",
        auth_header="OSDI-API-Token",
        credential_fields=("api_key",),
        operations={
            "list_people": VendorOperation("list_people", "List People", "GET", "/people"),
            "get_person": VendorOperation("get_person", "Get Person", "GET", "/people/{person_id}", ("person_id",)),
            "create_person": VendorOperation(
                "create_person", "Create Person", "POST", "/people", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "bamboo_hr": VendorSpec(
        key="bamboo_hr",
        display_name="BambooHR",
        description="BambooHR employee directory and records.",
        category="productivity",
        base_url="https://api.bamboohr.com/api/groups/{company_domain}/v1",
        auth_kind="basic",
        basic_user_field="api_key",
        default_password="x",
        credential_fields=("api_key",),
        extra_required=("company_domain",),
        operations={
            "list_employees": VendorOperation("list_employees", "List Employees", "GET", "/employees/directory"),
            "get_employee": VendorOperation("get_employee", "Get Employee", "GET", "/employees/{employee_id}", ("employee_id",)),
            "create_employee": VendorOperation(
                "create_employee", "Create Employee", "POST", "/employees", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "chargebee": VendorSpec(
        key="chargebee",
        display_name="Chargebee",
        description="Chargebee customers and subscription billing records.",
        category="finance",
        base_url="https://{site}.chargebee.com/api/v2",
        auth_kind="basic",
        basic_user_field="api_key",
        default_password="x",
        credential_fields=("api_key",),
        extra_required=("site",),
        operations={
            "list_customers": VendorOperation("list_customers", "List Customers", "GET", "/customers"),
            "get_customer": VendorOperation("get_customer", "Get Customer", "GET", "/customers/{customer_id}", ("customer_id",)),
            "create_customer": VendorOperation(
                "create_customer", "Create Customer", "POST", "/customers", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "circle_ci": VendorSpec(
        key="circle_ci",
        display_name="CircleCI",
        description="CircleCI users, projects, pipelines, and workflows.",
        category="developer",
        base_url="https://circleci.com/api/v2",
        auth_kind="header",
        auth_header="Circle-Token",
        credential_fields=("api_key",),
        operations={
            "get_user": VendorOperation("get_user", "Get Current User", "GET", "/me"),
            "list_pipelines": VendorOperation(
                "list_pipelines", "List Pipelines", "GET",
                "/project/{project_slug}/pipeline", ("project_slug",),
            ),
            "get_workflow": VendorOperation(
                "get_workflow", "Get Workflow", "GET", "/workflow/{workflow_id}", ("workflow_id",),
            ),
        },
    ),
    "confluence": VendorSpec(
        key="confluence",
        display_name="Confluence",
        description="Atlassian Confluence pages and content.",
        category="productivity",
        base_url="https://{site}.atlassian.net/wiki/rest/api",
        auth_kind="basic",
        basic_user_field="email",
        basic_password_field="api_token",
        credential_fields=("email", "api_token"),
        extra_required=("site",),
        operations={
            "list_pages": VendorOperation(
                "list_pages", "List Pages", "GET", "/content",
                description="List Confluence content; pass query params through payload.params.",
            ),
            "get_page": VendorOperation("get_page", "Get Page", "GET", "/content/{page_id}", ("page_id",)),
        },
    ),
    "contentful": VendorSpec(
        key="contentful",
        display_name="Contentful",
        description="Contentful Management API entries and content types.",
        category="productivity",
        base_url="https://api.contentful.com",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("space_id", "environment_id"),
        operations={
            "list_entries": VendorOperation(
                "list_entries", "List Entries", "GET",
                "/spaces/{space_id}/environments/{environment_id}/entries",
                ("space_id", "environment_id"),
            ),
            "get_entry": VendorOperation(
                "get_entry", "Get Entry", "GET",
                "/spaces/{space_id}/environments/{environment_id}/entries/{entry_id}",
                ("space_id", "environment_id", "entry_id"),
            ),
            "create_entry": VendorOperation(
                "create_entry", "Create Entry", "POST",
                "/spaces/{space_id}/environments/{environment_id}/entries",
                ("space_id", "environment_id"), retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "customer_io": VendorSpec(
        key="customer_io",
        display_name="Customer.io",
        description="Customer.io customers and messaging profiles.",
        category="communication",
        base_url="https://api.customer.io/v1",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "list_customers": VendorOperation("list_customers", "List Customers", "GET", "/customers"),
            "get_customer": VendorOperation("get_customer", "Get Customer", "GET", "/customers/{customer_id}", ("customer_id",)),
        },
    ),
    "databricks": VendorSpec(
        key="databricks",
        display_name="Databricks",
        description="Databricks clusters and workspace resources.",
        category="database",
        base_url="https://{workspace}.cloud.databricks.com/api/2.0",
        auth_kind="bearer",
        credential_fields=("access_token",),
        extra_required=("workspace",),
        operations={
            "list_clusters": VendorOperation("list_clusters", "List Clusters", "GET", "/clusters/list"),
            "get_cluster": VendorOperation("get_cluster", "Get Cluster", "GET", "/clusters/get", ("cluster_id",)),
        },
    ),
    "freshservice": VendorSpec(
        key="freshservice",
        display_name="Freshservice",
        description="Freshservice service-desk tickets and requests.",
        category="productivity",
        base_url="https://{domain}.freshservice.com/api/v2",
        auth_kind="basic",
        basic_user_field="api_key",
        default_password="x",
        credential_fields=("api_key",),
        extra_required=("domain",),
        operations={
            "list_tickets": VendorOperation("list_tickets", "List Tickets", "GET", "/tickets"),
            "get_ticket": VendorOperation("get_ticket", "Get Ticket", "GET", "/tickets/{ticket_id}", ("ticket_id",)),
            "create_ticket": VendorOperation(
                "create_ticket", "Create Ticket", "POST", "/tickets", (),
                retryable=False, idempotency="non_idempotent",
            ),
        },
    ),
    "bitly": VendorSpec(
        key="bitly",
        display_name="Bitly",
        description="Bitly short links and analytics.",
        category="communication",
        base_url="https://api-ssl.bitly.com/v4",
        auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "get_bitlink": VendorOperation("get_bitlink", "Get Bitlink", "GET", "/bitlinks/{bitlink}", ("bitlink",)),
            "shorten": VendorOperation(
                "shorten", "Shorten Link", "POST", "/shorten", (),
                retryable=False, idempotency="non_idempotent",
            ),
            "get_clicks": VendorOperation(
                "get_clicks", "Get Clicks", "GET", "/bitlinks/{bitlink}/clicks",
                ("bitlink",),
            ),
        },
    ),
    "adalo": VendorSpec(
        key="adalo",
        display_name="Adalo",
        description="Adalo collections and rows.",
        category="database",
        base_url="https://api.adalo.com/v0/apps/{app_id}",
        auth_kind="header",
        auth_header="Authorization",
        auth_prefix="Bearer ",
        credential_fields=("api_key",),
        extra_required=("app_id",),
        operations={
            "list_rows": VendorOperation("list_rows", "List Rows", "GET", "/collections/{collection_id}", ("collection_id",)),
            "get_row": VendorOperation("get_row", "Get Row", "GET", "/collections/{collection_id}/{row_id}", ("collection_id", "row_id")),
            "create_row": VendorOperation("create_row", "Create Row", "POST", "/collections/{collection_id}", ("collection_id",), retryable=False, idempotency="non_idempotent"),
        },
    ),
    "affinity": VendorSpec(
        key="affinity",
        display_name="Affinity",
        description="Affinity CRM persons and organizations.",
        category="crm",
        base_url="https://api.affinity.co",
        auth_kind="basic",
        basic_password_field="api_key",
        credential_fields=("api_key",),
        operations={
            "list_persons": VendorOperation("list_persons", "List Persons", "GET", "/persons"),
            "get_person": VendorOperation("get_person", "Get Person", "GET", "/persons/{person_id}", ("person_id",)),
            "create_person": VendorOperation("create_person", "Create Person", "POST", "/persons", (), retryable=False, idempotency="non_idempotent"),
        },
    ),
    "agile_crm": VendorSpec(
        key="agile_crm",
        display_name="Agile CRM",
        description="Agile CRM contacts and deals.",
        category="crm",
        base_url="https://{domain}.agilecrm.com/dev/api",
        auth_kind="basic",
        basic_user_field="email",
        basic_password_field="api_key",
        credential_fields=("email", "api_key"),
        extra_required=("domain",),
        operations={
            "list_contacts": VendorOperation("list_contacts", "List Contacts", "GET", "/contacts"),
            "get_contact": VendorOperation("get_contact", "Get Contact", "GET", "/contacts/{contact_id}", ("contact_id",)),
            "create_contact": VendorOperation("create_contact", "Create Contact", "POST", "/contacts", (), retryable=False, idempotency="non_idempotent"),
        },
    ),
    "airtop": VendorSpec(
        key="airtop",
        display_name="Airtop",
        description="Airtop browser automation sessions.",
        category="developer",
        base_url="https://api.airtop.ai/api/v1",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "list_sessions": VendorOperation("list_sessions", "List Sessions", "GET", "/sessions"),
            "get_session": VendorOperation("get_session", "Get Session", "GET", "/sessions/{session_id}", ("session_id",)),
        },
    ),
    "bannerbear": VendorSpec(
        key="bannerbear",
        display_name="Bannerbear",
        description="Bannerbear images and templates.",
        category="communication",
        base_url="https://api.bannerbear.com/v2",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "list_images": VendorOperation("list_images", "List Images", "GET", "/images"),
            "get_image": VendorOperation("get_image", "Get Image", "GET", "/images/{image_id}", ("image_id",)),
            "list_templates": VendorOperation("list_templates", "List Templates", "GET", "/templates"),
        },
    ),
    "baserow": VendorSpec(
        key="baserow",
        display_name="Baserow",
        description="Baserow database table rows.",
        category="database",
        base_url="https://api.baserow.io/api",
        auth_kind="header",
        auth_header="Authorization",
        auth_prefix="Token ",
        credential_fields=("api_key",),
        operations={
            "list_rows": VendorOperation("list_rows", "List Rows", "GET", "/database/rows/table/{table_id}/", ("table_id",)),
            "get_row": VendorOperation("get_row", "Get Row", "GET", "/database/rows/table/{table_id}/{row_id}/", ("table_id", "row_id")),
        },
    ),
    "brandfetch": VendorSpec(
        key="brandfetch",
        display_name="Brandfetch",
        description="Brandfetch brand identity data.",
        category="marketing",
        base_url="https://api.brandfetch.io/v2",
        auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "get_brand": VendorOperation("get_brand", "Get Brand", "GET", "/brands/{domain}", ("domain",)),
            "search_brand": VendorOperation("search_brand", "Search Brand", "GET", "/brands/search/{name}", ("name",)),
        },
    ),
    "bubble": VendorSpec(
        key="bubble",
        display_name="Bubble",
        description="Bubble Data API objects.",
        category="database",
        base_url="https://{app_name}.bubbleapps.io/api/1.1",
        auth_kind="bearer",
        credential_fields=("api_token",),
        extra_required=("app_name",),
        operations={
            "list_objects": VendorOperation("list_objects", "List Objects", "GET", "/obj/{type}", ("type",)),
            "get_object": VendorOperation("get_object", "Get Object", "GET", "/obj/{type}/{object_id}", ("type", "object_id")),
        },
    ),
    "dhl": VendorSpec(
        key="dhl",
        display_name="DHL",
        description="DHL shipment tracking.",
        category="communication",
        base_url="https://api-eu.dhl.com",
        auth_kind="header",
        auth_header="DHL-API-Key",
        credential_fields=("api_key",),
        operations={
            "track_shipment": VendorOperation("track_shipment", "Track Shipment", "GET", "/track/shipments"),
        },
    ),
    "figma": VendorSpec(
        key="figma",
        display_name="Figma",
        description="Figma files and comments.",
        category="developer",
        base_url="https://api.figma.com/v1",
        auth_kind="header",
        auth_header="X-Figma-Token",
        credential_fields=("api_key",),
        operations={
            "get_me": VendorOperation("get_me", "Get Current User", "GET", "/me"),
            "get_file": VendorOperation("get_file", "Get File", "GET", "/files/{file_key}", ("file_key",)),
            "list_comments": VendorOperation("list_comments", "List Comments", "GET", "/files/{file_key}/comments", ("file_key",)),
        },
    ),
    "drift": VendorSpec(
        key="drift", display_name="Drift", description="Drift conversations and contacts.",
        category="communication", base_url="https://driftapi.com", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_contacts": VendorOperation("list_contacts", "List Contacts", "GET", "/contacts"),
            "get_contact": VendorOperation("get_contact", "Get Contact", "GET", "/contacts/{contact_id}", ("contact_id",)),
        },
    ),
    "dropcontact": VendorSpec(
        key="dropcontact", display_name="Dropcontact", description="Dropcontact email enrichment.",
        category="marketing", base_url="https://api.dropcontact.io", auth_kind="header",
        auth_header="X-Access-Token", credential_fields=("api_key",),
        operations={
            "enrich_batch": VendorOperation("enrich_batch", "Enrich Batch", "POST", "/batch", (), retryable=False, idempotency="non_idempotent"),
        },
    ),
    "egoi": VendorSpec(
        key="egoi", display_name="Egoi", description="Egoi lists and contacts.",
        category="marketing", base_url="https://api.egoiapp.com", auth_kind="header",
        auth_header="ApiKey", credential_fields=("api_key",),
        operations={
            "list_lists": VendorOperation("list_lists", "List Lists", "GET", "/lists"),
            "list_contacts": VendorOperation("list_contacts", "List Contacts", "GET", "/contacts"),
        },
    ),
    "emelia": VendorSpec(
        key="emelia", display_name="Emelia", description="Emelia campaigns and contacts.",
        category="marketing", base_url="https://api.emelia.io", auth_kind="header",
        auth_header="X-API-KEY", credential_fields=("api_key",),
        operations={
            "list_campaigns": VendorOperation("list_campaigns", "List Campaigns", "GET", "/campaigns"),
            "get_campaign": VendorOperation("get_campaign", "Get Campaign", "GET", "/campaigns/{campaign_id}", ("campaign_id",)),
        },
    ),
    "harvest": VendorSpec(
        key="harvest", display_name="Harvest", description="Harvest time tracking and clients.",
        category="productivity", base_url="https://api.harvestapp.com/v2", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "get_me": VendorOperation("get_me", "Get Current User", "GET", "/users/me"),
            "list_clients": VendorOperation("list_clients", "List Clients", "GET", "/clients"),
        },
    ),
    "lemlist": VendorSpec(
        key="lemlist", display_name="Lemlist", description="Lemlist campaigns and leads.",
        category="marketing", base_url="https://api.lemlist.com/api", auth_kind="basic",
        basic_user_field="api_key", credential_fields=("api_key",),
        operations={
            "list_campaigns": VendorOperation("list_campaigns", "List Campaigns", "GET", "/campaigns"),
            "get_campaign": VendorOperation("get_campaign", "Get Campaign", "GET", "/campaigns/{campaign_id}", ("campaign_id",)),
        },
    ),
    "mailer_lite": VendorSpec(
        key="mailer_lite", display_name="MailerLite", description="MailerLite groups and subscribers.",
        category="marketing", base_url="https://api.mailerlite.com/api/v2", auth_kind="header",
        auth_header="X-MailerLite-ApiKey", credential_fields=("api_key",),
        operations={
            "list_groups": VendorOperation("list_groups", "List Groups", "GET", "/groups"),
            "get_subscriber": VendorOperation("get_subscriber", "Get Subscriber", "GET", "/subscribers/{email}", ("email",)),
        },
    ),
    "mailgun": VendorSpec(
        key="mailgun", display_name="Mailgun", description="Mailgun domains and messages.",
        category="communication", base_url="https://api.mailgun.net/v3", auth_kind="basic",
        basic_user_literal="api", basic_password_field="api_key", credential_fields=("api_key",),
        operations={
            "list_domains": VendorOperation("list_domains", "List Domains", "GET", "/domains"),
            "get_domain": VendorOperation("get_domain", "Get Domain", "GET", "/domains/{domain}", ("domain",)),
        },
    ),
    "mattermost": VendorSpec(
        key="mattermost", display_name="Mattermost", description="Mattermost users and teams.",
        category="communication", base_url="https://{host}/api/v4", auth_kind="bearer",
        credential_fields=("access_token",), extra_required=("host",),
        operations={
            "get_me": VendorOperation("get_me", "Get Current User", "GET", "/users/me"),
            "list_teams": VendorOperation("list_teams", "List Teams", "GET", "/teams"),
        },
    ),
    "noco_d_b": VendorSpec(
        key="noco_d_b", display_name="NocoDB", description="NocoDB bases and tables.",
        category="database", base_url="https://{host}/api/v2", auth_kind="header",
        auth_header="xc-token", credential_fields=("api_key",), extra_required=("host",),
        operations={
            "list_bases": VendorOperation("list_bases", "List Bases", "GET", "/meta/bases"),
            "list_tables": VendorOperation("list_tables", "List Tables", "GET", "/meta/bases/{base_id}/tables", ("base_id",)),
        },
    ),
    "mailjet": VendorSpec(
        key="mailjet", display_name="Mailjet", description="Mailjet contacts and lists.",
        category="communication", base_url="https://api.mailjet.com", auth_kind="basic",
        basic_user_field="api_key", basic_password_field="api_secret",
        credential_fields=("api_key", "api_secret"),
        operations={
            "list_contacts": VendorOperation("list_contacts", "List Contacts", "GET", "/v3/REST/contact"),
            "list_lists": VendorOperation("list_lists", "List Lists", "GET", "/v3/REST/list"),
        },
    ),
    "message_bird": VendorSpec(
        key="message_bird", display_name="MessageBird", description="MessageBird contacts and SMS.",
        category="communication", base_url="https://rest.messagebird.com", auth_kind="header",
        auth_header="Authorization", auth_prefix="AccessKey ", credential_fields=("api_key",),
        operations={
            "list_contacts": VendorOperation("list_contacts", "List Contacts", "GET", "/contacts"),
            "send_message": VendorOperation("send_message", "Send Message", "POST", "/messages", (), retryable=False, idempotency="non_idempotent"),
        },
    ),
    "netlify": VendorSpec(
        key="netlify", display_name="Netlify", description="Netlify sites and deploys.",
        category="developer", base_url="https://api.netlify.com/api/v1", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_sites": VendorOperation("list_sites", "List Sites", "GET", "/sites"),
            "get_site": VendorOperation("get_site", "Get Site", "GET", "/sites/{site_id}", ("site_id",)),
        },
    ),
    "okta": VendorSpec(
        key="okta", display_name="Okta", description="Okta users and groups.",
        category="developer", base_url="https://{host}/api/v1", auth_kind="header",
        auth_header="Authorization", auth_prefix="SSWS ", credential_fields=("api_key",),
        extra_required=("host",),
        operations={
            "list_users": VendorOperation("list_users", "List Users", "GET", "/users"),
            "get_user": VendorOperation("get_user", "Get User", "GET", "/users/{user_id}", ("user_id",)),
        },
    ),
    "onfleet": VendorSpec(
        key="onfleet", display_name="Onfleet", description="Onfleet workers and tasks.",
        category="communication", base_url="https://onfleet.com/api/v2", auth_kind="basic",
        basic_user_field="api_key", credential_fields=("api_key",),
        operations={
            "list_workers": VendorOperation("list_workers", "List Workers", "GET", "/workers"),
            "list_tasks": VendorOperation("list_tasks", "List Tasks", "GET", "/tasks"),
        },
    ),
    "pushbullet": VendorSpec(
        key="pushbullet", display_name="Pushbullet", description="Pushbullet pushes and devices.",
        category="communication", base_url="https://api.pushbullet.com/v2", auth_kind="header",
        auth_header="Access-Token", credential_fields=("api_key",),
        operations={
            "get_me": VendorOperation("get_me", "Get Current User", "GET", "/users/me"),
            "list_pushes": VendorOperation("list_pushes", "List Pushes", "GET", "/pushes"),
        },
    ),
    "travis_ci": VendorSpec(
        key="travis_ci", display_name="Travis CI", description="Travis CI builds and repositories.",
        category="developer", base_url="https://api.travis-ci.com", auth_kind="header",
        auth_header="Authorization", auth_prefix="token ", credential_fields=("api_key",),
        operations={
            "get_user": VendorOperation("get_user", "Get Current User", "GET", "/user"),
            "list_repos": VendorOperation("list_repos", "List Repositories", "GET", "/repos"),
        },
    ),
    "webflow": VendorSpec(
        key="webflow", display_name="Webflow", description="Webflow sites and collections.",
        category="productivity", base_url="https://api.webflow.com/v2", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_sites": VendorOperation("list_sites", "List Sites", "GET", "/sites"),
            "get_site": VendorOperation("get_site", "Get Site", "GET", "/sites/{site_id}", ("site_id",)),
        },
    ),
    "wise": VendorSpec(
        key="wise", display_name="Wise", description="Wise profiles and transfers.",
        category="finance", base_url="https://api.wise.com", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_profiles": VendorOperation("list_profiles", "List Profiles", "GET", "/v1/profiles"),
            "get_profile": VendorOperation("get_profile", "Get Profile", "GET", "/v1/profiles/{profile_id}", ("profile_id",)),
        },
    ),
    "zammad": VendorSpec(
        key="zammad", display_name="Zammad", description="Zammad tickets and users.",
        category="productivity", base_url="https://{host}/api/v1", auth_kind="header",
        auth_header="Authorization", auth_prefix="Token token=", credential_fields=("access_token",),
        extra_required=("host",),
        operations={
            "list_tickets": VendorOperation("list_tickets", "List Tickets", "GET", "/tickets"),
            "get_ticket": VendorOperation("get_ticket", "Get Ticket", "GET", "/tickets/{ticket_id}", ("ticket_id",)),
        },
    ),
    "open_ai": VendorSpec(
        key="open_ai", display_name="OpenAI API", description="OpenAI models and chat completions.",
        category="ai", base_url="https://api.openai.com/v1", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_models": VendorOperation("list_models", "List Models", "GET", "/models"),
            "chat_completion": VendorOperation("chat_completion", "Chat Completion", "POST", "/chat/completions", (), retryable=False, idempotency="non_idempotent"),
        },
    ),
    "paddle": VendorSpec(
        key="paddle", display_name="Paddle", description="Paddle products and customers.",
        category="finance", base_url="https://api.paddle.com", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_products": VendorOperation("list_products", "List Products", "GET", "/products"),
            "list_customers": VendorOperation("list_customers", "List Customers", "GET", "/customers"),
        },
    ),
    "sms77": VendorSpec(
        key="sms77", display_name="seven", description="seven SMS messaging.",
        category="communication", base_url="https://gateway.seven.io/api", auth_kind="header",
        auth_header="X-Api-Key", credential_fields=("api_key",),
        operations={
            "send_sms": VendorOperation("send_sms", "Send SMS", "POST", "/sms", (), retryable=False, idempotency="non_idempotent"),
        },
    ),
    "taiga": VendorSpec(
        key="taiga", display_name="Taiga", description="Taiga projects and issues.",
        category="productivity", base_url="https://api.taiga.io/api/v1", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_projects": VendorOperation("list_projects", "List Projects", "GET", "/projects"),
            "get_project": VendorOperation("get_project", "Get Project", "GET", "/projects/{project_id}", ("project_id",)),
        },
    ),
    "monica_crm": VendorSpec(
        key="monica_crm", display_name="Monica CRM", description="Monica contacts and activities.",
        category="crm", base_url="https://app.monicahq.com/api", auth_kind="bearer",
        credential_fields=("access_token",),
        operations={
            "list_contacts": VendorOperation("list_contacts", "List Contacts", "GET", "/contacts"),
            "get_contact": VendorOperation("get_contact", "Get Contact", "GET", "/contacts/{contact_id}", ("contact_id",)),
        },
    ),
    "nasa": VendorSpec(
        key="nasa", display_name="NASA", description="NASA public APIs.",
        category="analytics", base_url="https://api.nasa.gov", auth_kind="query",
        query_param="api_key", credential_fields=("api_key",),
        operations={
            "astronomy_picture": VendorOperation("astronomy_picture", "Astronomy Picture of the Day", "GET", "/planetary/apod"),
        },
    ),
    "npm": VendorSpec(
        key="npm", display_name="npm", description="npm package registry.",
        category="developer", base_url="https://registry.npmjs.org", auth_kind="none",
        credential_fields=(),
        operations={
            "get_package": VendorOperation("get_package", "Get Package", "GET", "/{package}", ("package",)),
        },
    ),
    "marketstack": VendorSpec(
        key="marketstack", display_name="Marketstack", description="Marketstack market data.",
        category="finance", base_url="https://api.marketstack.com/v1", auth_kind="query",
        query_param="access_key", credential_fields=("api_key",),
        operations={
            "eod": VendorOperation("eod", "End of Day", "GET", "/eod"),
        },
    ),
    "mailcheck": VendorSpec(
        key="mailcheck", display_name="Mailcheck", description="Mailcheck email verification.",
        category="marketing", base_url="https://api.mailcheck.co/v1", auth_kind="bearer",
        credential_fields=("api_key",),
        operations={
            "check_email": VendorOperation("check_email", "Check Email", "GET", "/check"),
        },
    ),
    "mautic": VendorSpec(
        key="mautic", display_name="Mautic", description="Mautic contacts and segments.",
        category="marketing", base_url="https://{host}/api", auth_kind="basic",
        basic_user_field="username", basic_password_field="password",
        credential_fields=("username", "password"), extra_required=("host",),
        operations={
            "list_contacts": VendorOperation("list_contacts", "List Contacts", "GET", "/contacts"),
            "list_segments": VendorOperation("list_segments", "List Segments", "GET", "/segments"),
        },
    ),
}


class VendorRESTParams(BaseModel):
    operation: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)


class VendorRESTConnector(ConnectorSDK):
    """Small native connector with fixed vendor host and auth contract."""

    implementation_kind = "native"

    def __init__(self, spec: VendorSpec) -> None:
        self.spec = spec
        super().__init__(spec.key, spec.display_name, spec.description)
        self.version = "1.0.0"
        self.category = spec.category

    @property
    def node_types(self) -> list[str]:
        return [self.spec.key]

    async def connect(self, config: dict[str, Any]) -> bool:
        self.status = "connected" if any(config.get(k) for k in self.spec.credential_fields) else "initialized"
        return self.status == "connected"

    async def disconnect(self) -> None:
        self.status = "disconnected"
        self._metadata.clear()

    def _value(self, payload: dict[str, Any], creds: dict[str, Any], name: str) -> Any:
        value = payload.get(name)
        if value is None:
            value = creds.get(name)
        return value

    def _format(self, template: str, payload: dict[str, Any], creds: dict[str, Any]) -> str:
        values = {**creds, **payload}
        missing = [name for name in self.spec.extra_required if not values.get(name)]
        missing += [
            name for name in template.split("{")[1:]
            if not values.get(name.split("}", 1)[0])
        ]
        if missing:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"{self.display_name} requires: {', '.join(sorted(set(missing)))}.",
                retryable=False,
            )
        try:
            return template.format(**values)
        except KeyError as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"{self.display_name} missing path field: {exc.args[0]}.",
                retryable=False,
            ) from exc

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = VendorRESTParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Invalid {self.display_name} payload: {exc}",
                retryable=False,
            ) from exc
        op_key = (operation or params.operation or "").lower()
        op = self.spec.operations.get(op_key)
        if op is None:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"{self.display_name} operation '{op_key}' is not supported.",
                retryable=False,
            )
        creds: dict[str, Any] = {}
        if context and context.get("credentials"):
            creds = context["credentials"].get(self.spec.key) or {}

        path = self._format(op.path, params.params, creds)
        base = self._format(self.spec.base_url, params.params, creds).rstrip("/")
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.spec.auth_kind == "bearer":
            token = str(
                creds.get("access_token") or creds.get("api_key") or creds.get("api_token") or ""
            ).strip()
            if not token:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    f"{self.display_name} requires an access token.",
                    retryable=False,
                )
            headers["Authorization"] = f"Bearer {token}"
        elif self.spec.auth_kind == "header":
            token = str(creds.get("api_key") or creds.get("access_token") or "").strip()
            if not token:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    f"{self.display_name} requires an API key.",
                    retryable=False,
                )
            headers[self.spec.auth_header] = self.spec.auth_prefix + token
        elif self.spec.auth_kind == "query":
            token = str(creds.get(self.spec.query_param) or creds.get("api_key") or "").strip()
            if not token:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    f"{self.display_name} requires an API key.",
                    retryable=False,
                )
        elif self.spec.auth_kind == "basic":
            username_value = self.spec.basic_user_literal or (
                creds.get(self.spec.basic_user_field) if self.spec.basic_user_field else ""
            )
            username = str(username_value or "").strip()
            password = str(
                creds.get(self.spec.basic_password_field) or self.spec.default_password or ""
            )
            if (self.spec.basic_user_field or self.spec.basic_user_literal) and not username:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    f"{self.display_name} requires a username/API key.",
                    retryable=False,
                )
            headers["Authorization"] = "Basic " + base64.b64encode(
                f"{username}:{password}".encode()
            ).decode()

        query = dict(params.params) if op.method == "GET" and params.params else {}
        if self.spec.auth_kind == "query":
            query[self.spec.query_param] = creds.get(self.spec.query_param) or creds.get("api_key")
        body = params.body
        if op.method in {"POST", "PUT", "PATCH"}:
            headers["Content-Type"] = "application/json"
            body = body if body is not None else params.params
        try:
            from app.security.safe_http_client import get_safe_http_client

            client = get_safe_http_client()
            response = await client.request(
                op.method,
                f"{base}{path}",
                headers=headers,
                params=query or None,
                json=body if op.method in {"POST", "PUT", "PATCH"} else None,
                timeout=params.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                f"{self.display_name} request timed out.",
                retryable=True,
            ) from exc
        except ConnectorError:
            raise
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"{self.display_name} request failed: {exc}",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            code = (
                ConnectorErrorCode.AUTH_FAILED if response.status_code in (401, 403)
                else ConnectorErrorCode.NOT_FOUND if response.status_code == 404
                else ConnectorErrorCode.RATE_LIMITED if response.status_code == 429
                else ConnectorErrorCode.UNAVAILABLE if response.status_code >= 500
                else ConnectorErrorCode.BAD_REQUEST
            )
            raise make_connector_error(
                code,
                f"{self.display_name} returned HTTP {response.status_code}: {response.text[:200]}",
                retryable=response.status_code in (429, 500, 502, 503, 504),
            )
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = {"text": response.text}
        return {
            "success": True,
            "connector": self.spec.key,
            "operation": op.key,
            "status_code": response.status_code,
            "data": data,
        }


def build_vendor_connectors() -> list[tuple[VendorRESTConnector, ConnectorDefinitionV1]]:
    out: list[tuple[VendorRESTConnector, ConnectorDefinitionV1]] = []
    for spec in VENDOR_SPECS.values():
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
        credential_properties = {
            field: {"type": "string", "title": field.replace("_", " ").title()}
            for field in spec.credential_fields
        }
        definition = ConnectorDefinitionV1(
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
                "batch": "catalog_conversion_1" if spec.key in BATCH1_KEYS else "catalog_conversion_2",
            },
        )
        out.append((VendorRESTConnector(spec), definition))
    return out
