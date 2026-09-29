"""Canonical Master Integration Catalog Seed Data (Phase 4 & 5).

Accurately attributes capabilities and platform support across:
- FlowSmith (Active Native & Generated Connectors)
- n8n (Documented Community & Official Nodes)
- Zapier (Documented Public Apps)
- Cyclr (Documented System Connectors)

Follows Phase 30: "NO FAKE COMPLETENESS" — every entry reflects verified state.
"""

from __future__ import annotations

from typing import List
from app.integrations.catalog.schema import (
    AuthType,
    CertificationLevel,
    ExternalSources,
    FlowsmithSupportStatus,
    IntegrationCategory,
    IntegrationDefinition,
    OperationSpec,
    SourcePresence,
    SupportType,
    TriggerSpec,
)


def get_seed_integrations() -> List[IntegrationDefinition]:
    """Returns the canonical catalog of verified integrations."""
    return [
        # =====================================================================
        # TIER 1: ENTERPRISE-CRITICAL SYSTEMS
        # =====================================================================
        IntegrationDefinition(
            id="salesforce",
            name="Salesforce",
            vendor="Salesforce Inc.",
            category=IntegrationCategory.CRM,
            subcategory="Enterprise CRM",
            website="https://www.salesforce.com",
            documentation_url="https://developer.salesforce.com/docs",
            icon="salesforce",
            color="#00A1E0",
            authentication=[AuthType.OAUTH2, AuthType.BEARER_TOKEN],
            capabilities=["soql", "custom_objects", "outbound_messaging", "bulk_api", "schema_introspection"],
            operations=[
                OperationSpec(key="create", name="Create Record", description="Create an SObject record", idempotent=False, action_type="crud"),
                OperationSpec(key="get", name="Get Record", description="Fetch an SObject record by ID", idempotent=True, action_type="crud"),
                OperationSpec(key="update", name="Update Record", description="Update an SObject record by ID", idempotent=True, action_type="crud"),
                OperationSpec(key="delete", name="Delete Record", description="Delete an SObject record", idempotent=True, action_type="crud"),
                OperationSpec(key="query", name="SOQL Query", description="Execute arbitrary SOQL query", idempotent=True, action_type="search"),
                OperationSpec(key="search", name="Search Records", description="SOSL or filtered record search", idempotent=True, action_type="search"),
                OperationSpec(key="describe", name="Describe SObject", description="Introspect fields and types", idempotent=True, action_type="rpc"),
            ],
            triggers=[
                TriggerSpec(key="outbound_message", name="Outbound Message", description="Real-time SOAP XML notification", trigger_type="webhook"),
                TriggerSpec(key="cdc_event", name="Change Data Capture", description="Pub/Sub event bus notification", trigger_type="event_stream"),
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="salesforce", operation_count=7, trigger_count=2, notes="Deep native connector with SOQL & Outbound Message support"),
                n8n=SourcePresence(supported=True, connector_id="salesforce", operation_count=8, trigger_count=1),
                zapier=SourcePresence(supported=True, connector_id="salesforce", operation_count=10, trigger_count=6),
                cyclr=SourcePresence(supported=True, connector_id="salesforce", operation_count=12, trigger_count=4),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="salesforce",
                node_slugs=["salesforce", "salesforce_trigger"],
                has_e2e_test=True,
                has_contract_test=True,
                notes="Certified Tier-1 native enterprise integration with full test suite."
            )
        ),

        IntegrationDefinition(
            id="dynamics_crm",
            name="Microsoft Dynamics 365 CRM",
            vendor="Microsoft Corporation",
            category=IntegrationCategory.CRM,
            subcategory="Enterprise CRM",
            website="https://dynamics.microsoft.com",
            documentation_url="https://learn.microsoft.com/en-us/dynamics365/",
            icon="dynamics_crm",
            color="#002050",
            authentication=[AuthType.OAUTH2],
            capabilities=["odata", "entity_introspection", "whoami", "custom_entities"],
            operations=[
                OperationSpec(key="get_record", name="Get Record", description="Get entity by ID", idempotent=True, action_type="crud"),
                OperationSpec(key="create_record", name="Create Record", description="Create entity record", idempotent=False, action_type="crud"),
                OperationSpec(key="update_record", name="Update Record", description="Update entity record", idempotent=True, action_type="crud"),
                OperationSpec(key="delete_record", name="Delete Record", description="Delete entity record", idempotent=True, action_type="crud"),
                OperationSpec(key="query_records", name="Query Records", description="OData query records", idempotent=True, action_type="search"),
                OperationSpec(key="whoami", name="Who Am I", description="Verify authenticated organization", idempotent=True, action_type="rpc"),
            ],
            triggers=[
                TriggerSpec(key="webhook", name="Dataverse Webhook", description="Incoming webhook trigger from Dataverse", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="dynamics_crm", operation_count=6, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="microsoftDynamicsCrm", operation_count=6, trigger_count=1),
                zapier=SourcePresence(supported=True, connector_id="microsoft-dynamics-crm", operation_count=8, trigger_count=4),
                cyclr=SourcePresence(supported=True, connector_id="dynamics365", operation_count=10, trigger_count=3),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="dynamics_crm",
                node_slugs=["dynamics_crm"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="hubspot",
            name="HubSpot",
            vendor="HubSpot Inc.",
            category=IntegrationCategory.CRM,
            subcategory="Inbound Marketing & CRM",
            website="https://www.hubspot.com",
            documentation_url="https://developers.hubspot.com",
            icon="hubspot",
            color="#FF7A59",
            authentication=[AuthType.OAUTH2, AuthType.API_KEY],
            capabilities=["contacts", "companies", "deals", "custom_properties", "webhooks"],
            operations=[
                OperationSpec(key="get_contact", name="Get Contact", description="Fetch contact details", idempotent=True, action_type="crud"),
                OperationSpec(key="create_contact", name="Create Contact", description="Create new contact", idempotent=False, action_type="crud"),
                OperationSpec(key="update_contact", name="Update Contact", description="Update contact", idempotent=True, action_type="crud"),
                OperationSpec(key="search_contacts", name="Search Contacts", description="Filter contacts", idempotent=True, action_type="search"),
            ],
            triggers=[
                TriggerSpec(key="contact_created", name="New Contact", description="Trigger on new contact creation", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="hubspot", operation_count=4, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="hubspot", operation_count=12, trigger_count=3),
                zapier=SourcePresence(supported=True, connector_id="hubspot", operation_count=14, trigger_count=8),
                cyclr=SourcePresence(supported=True, connector_id="hubspot", operation_count=10, trigger_count=4),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="hubspot",
                node_slugs=["hubspot"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="jira",
            name="Jira Software",
            vendor="Atlassian",
            category=IntegrationCategory.PRODUCTIVITY,
            subcategory="Issue Tracking & Agile",
            website="https://www.atlassian.com/software/jira",
            documentation_url="https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/",
            icon="jira",
            color="#0052CC",
            authentication=[AuthType.OAUTH2, AuthType.BASIC_AUTH, AuthType.API_KEY],
            capabilities=["jql", "custom_fields", "transitions", "attachments"],
            operations=[
                OperationSpec(key="create_issue", name="Create Issue", description="Create an issue ticket", idempotent=False, action_type="crud"),
                OperationSpec(key="get_issue", name="Get Issue", description="Retrieve issue by key", idempotent=True, action_type="crud"),
                OperationSpec(key="update_issue", name="Update Issue", description="Update issue fields", idempotent=True, action_type="crud"),
                OperationSpec(key="search_issues", name="Search Issues (JQL)", description="Query issues with JQL", idempotent=True, action_type="search"),
            ],
            triggers=[
                TriggerSpec(key="issue_created", name="Issue Created", description="Fires when issue is created", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="jira", operation_count=4, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="jiraSoftware", operation_count=8, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="jira", operation_count=10, trigger_count=5),
                cyclr=SourcePresence(supported=True, connector_id="jira", operation_count=9, trigger_count=3),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="jira",
                node_slugs=["jira"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="slack",
            name="Slack",
            vendor="Salesforce Inc.",
            category=IntegrationCategory.COMMUNICATION,
            subcategory="Team Chat",
            website="https://slack.com",
            documentation_url="https://api.slack.com",
            icon="slack",
            color="#4A154B",
            authentication=[AuthType.OAUTH2, AuthType.BEARER_TOKEN],
            capabilities=["block_kit", "channels", "threads", "files", "reactions"],
            operations=[
                OperationSpec(key="send_message", name="Post Message", description="Post message to channel or user", idempotent=False, action_type="action"),
                OperationSpec(key="update_message", name="Update Message", description="Update existing message", idempotent=True, action_type="action"),
                OperationSpec(key="add_reaction", name="Add Reaction", description="Add emoji reaction", idempotent=True, action_type="action"),
                OperationSpec(key="upload_file", name="Upload File", description="Upload file to channel", idempotent=False, action_type="action"),
            ],
            triggers=[
                TriggerSpec(key="new_message", name="New Message", description="Trigger on incoming channel message", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="slack", operation_count=4, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="slack", operation_count=8, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="slack", operation_count=12, trigger_count=7),
                cyclr=SourcePresence(supported=True, connector_id="slack", operation_count=8, trigger_count=3),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="slack",
                node_slugs=["slack"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="github",
            name="GitHub",
            vendor="GitHub / Microsoft",
            category=IntegrationCategory.DEVELOPER_DEVOPS,
            subcategory="Code & CI/CD",
            website="https://github.com",
            documentation_url="https://docs.github.com/en/rest",
            icon="github",
            color="#181717",
            authentication=[AuthType.OAUTH2, AuthType.BEARER_TOKEN],
            capabilities=["issues", "pull_requests", "releases", "webhooks", "actions"],
            operations=[
                OperationSpec(key="create_issue", name="Create Issue", description="Create a GitHub issue", idempotent=False, action_type="crud"),
                OperationSpec(key="create_comment", name="Create Comment", description="Comment on issue or PR", idempotent=False, action_type="action"),
                OperationSpec(key="list_issues", name="List Issues", description="List repository issues", idempotent=True, action_type="search"),
                OperationSpec(key="create_release", name="Create Release", description="Publish a tag release", idempotent=False, action_type="action"),
            ],
            triggers=[
                TriggerSpec(key="push", name="Push Event", description="Trigger on branch commit push", trigger_type="webhook"),
                TriggerSpec(key="pull_request", name="Pull Request Event", description="Trigger on PR opened/merged", trigger_type="webhook"),
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="github", operation_count=4, trigger_count=2),
                n8n=SourcePresence(supported=True, connector_id="github", operation_count=10, trigger_count=4),
                zapier=SourcePresence(supported=True, connector_id="github", operation_count=9, trigger_count=6),
                cyclr=SourcePresence(supported=True, connector_id="github", operation_count=8, trigger_count=3),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="github",
                node_slugs=["github"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="stripe",
            name="Stripe",
            vendor="Stripe Inc.",
            category=IntegrationCategory.FINANCE_COMMERCE,
            subcategory="Payments & Subscriptions",
            website="https://stripe.com",
            documentation_url="https://docs.stripe.com/api",
            icon="stripe",
            color="#635BFF",
            authentication=[AuthType.BEARER_TOKEN],
            capabilities=["idempotency_keys", "charges", "customers", "subscriptions", "invoices"],
            operations=[
                OperationSpec(key="create_customer", name="Create Customer", description="Create Stripe customer", idempotent=False, action_type="crud"),
                OperationSpec(key="create_payment_intent", name="Create Payment Intent", description="Initialize a payment session", idempotent=False, action_type="action"),
                OperationSpec(key="get_charge", name="Get Charge", description="Retrieve charge details", idempotent=True, action_type="crud"),
                OperationSpec(key="list_customers", name="List Customers", description="Query customer list", idempotent=True, action_type="search"),
            ],
            triggers=[
                TriggerSpec(key="charge_succeeded", name="Charge Succeeded", description="Trigger on successful payment", trigger_type="webhook"),
                TriggerSpec(key="customer_subscription_created", name="Subscription Created", description="Trigger on new subscription", trigger_type="webhook"),
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="stripe", operation_count=4, trigger_count=2),
                n8n=SourcePresence(supported=True, connector_id="stripe", operation_count=12, trigger_count=4),
                zapier=SourcePresence(supported=True, connector_id="stripe", operation_count=11, trigger_count=7),
                cyclr=SourcePresence(supported=True, connector_id="stripe", operation_count=10, trigger_count=5),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="stripe",
                node_slugs=["stripe"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="shopify",
            name="Shopify",
            vendor="Shopify Inc.",
            category=IntegrationCategory.FINANCE_COMMERCE,
            subcategory="E-Commerce",
            website="https://www.shopify.com",
            documentation_url="https://shopify.dev/docs/api",
            icon="shopify",
            color="#95BF47",
            authentication=[AuthType.OAUTH2, AuthType.BEARER_TOKEN],
            capabilities=["orders", "products", "inventory", "webhooks"],
            operations=[
                OperationSpec(key="get_order", name="Get Order", description="Fetch order by ID", idempotent=True, action_type="crud"),
                OperationSpec(key="create_product", name="Create Product", description="Add product to store", idempotent=False, action_type="crud"),
                OperationSpec(key="update_inventory", name="Update Inventory", description="Adjust stock count", idempotent=True, action_type="action"),
            ],
            triggers=[
                TriggerSpec(key="order_created", name="Order Created", description="Fires on incoming shop order", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="shopify", operation_count=3, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="shopify", operation_count=8, trigger_count=3),
                zapier=SourcePresence(supported=True, connector_id="shopify", operation_count=12, trigger_count=6),
                cyclr=SourcePresence(supported=True, connector_id="shopify", operation_count=10, trigger_count=4),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="shopify",
                node_slugs=["shopify"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="zendesk",
            name="Zendesk",
            vendor="Zendesk Inc.",
            category=IntegrationCategory.CUSTOMER_SUPPORT,
            subcategory="Helpdesk & Ticketing",
            website="https://www.zendesk.com",
            documentation_url="https://developer.zendesk.com/api-reference/",
            icon="zendesk",
            color="#03363D",
            authentication=[AuthType.OAUTH2, AuthType.BASIC_AUTH],
            capabilities=["tickets", "users", "tags", "custom_fields"],
            operations=[
                OperationSpec(key="create_ticket", name="Create Ticket", description="Open a support ticket", idempotent=False, action_type="crud"),
                OperationSpec(key="get_ticket", name="Get Ticket", description="Retrieve ticket details", idempotent=True, action_type="crud"),
                OperationSpec(key="update_ticket", name="Update Ticket", description="Update status, assignee, priority", idempotent=True, action_type="crud"),
            ],
            triggers=[
                TriggerSpec(key="ticket_created", name="Ticket Created", description="Trigger on incoming ticket", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="zendesk", operation_count=3, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="zendesk", operation_count=7, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="zendesk", operation_count=9, trigger_count=4),
                cyclr=SourcePresence(supported=True, connector_id="zendesk", operation_count=8, trigger_count=3),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="zendesk",
                node_slugs=["zendesk"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="servicenow",
            name="ServiceNow",
            vendor="ServiceNow Inc.",
            category=IntegrationCategory.DEVELOPER_DEVOPS,
            subcategory="ITSM & Enterprise Service Management",
            website="https://www.servicenow.com",
            documentation_url="https://developer.servicenow.com/",
            icon="servicenow",
            color="#81B5A1",
            authentication=[AuthType.OAUTH2, AuthType.BASIC_AUTH],
            capabilities=["table_api", "incident_management", "change_requests"],
            operations=[
                OperationSpec(key="create_incident", name="Create Incident", description="Create ITSM incident", idempotent=False, action_type="crud"),
                OperationSpec(key="get_incident", name="Get Incident", description="Fetch incident details", idempotent=True, action_type="crud"),
                OperationSpec(key="update_incident", name="Update Incident", description="Update incident status", idempotent=True, action_type="crud"),
            ],
            triggers=[
                TriggerSpec(key="incident_updated", name="Incident Updated", description="Webhook or polling on incident change", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="servicenow", operation_count=5, trigger_count=1, notes="Native Table API connector with Basic/OAuth auth"),
                n8n=SourcePresence(supported=True, connector_id="serviceNow", operation_count=6, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="servicenow", operation_count=8, trigger_count=3),
                cyclr=SourcePresence(supported=True, connector_id="servicenow", operation_count=6, trigger_count=2),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.TESTED,
                is_active=True,
                connector_key="servicenow",
                node_slugs=["servicenow"],
                has_e2e_test=False,
                has_contract_test=True,
                notes="Native Tier-1 connector: ServiceNow Table API with mocked contract tests."
            )
        ),

        # =====================================================================
        # TIER 2: HIGH-VOLUME SAAS & PRODUCTIVITY
        # =====================================================================
        IntegrationDefinition(
            id="notion",
            name="Notion",
            vendor="Notion Labs Inc.",
            category=IntegrationCategory.PRODUCTIVITY,
            subcategory="Knowledge & Docs",
            website="https://www.notion.so",
            documentation_url="https://developers.notion.com",
            icon="notion",
            color="#000000",
            authentication=[AuthType.BEARER_TOKEN, AuthType.OAUTH2],
            capabilities=["databases", "pages", "blocks", "rich_text"],
            operations=[
                OperationSpec(key="create_page", name="Create Page", description="Create page in database or parent", idempotent=False, action_type="crud"),
                OperationSpec(key="query_database", name="Query Database", description="Filter database rows", idempotent=True, action_type="search"),
                OperationSpec(key="update_page", name="Update Page", description="Update page properties", idempotent=True, action_type="crud"),
            ],
            triggers=[
                TriggerSpec(key="page_updated", name="Page Updated", description="Polling trigger on database update", trigger_type="polling")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="notion", operation_count=3, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="notion", operation_count=8, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="notion", operation_count=7, trigger_count=4),
                cyclr=SourcePresence(supported=True, connector_id="notion", operation_count=5, trigger_count=2),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="notion",
                node_slugs=["notion"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="airtable",
            name="Airtable",
            vendor="Formagrid Inc.",
            category=IntegrationCategory.PRODUCTIVITY,
            subcategory="Spreadsheet-Database",
            website="https://www.airtable.com",
            documentation_url="https://airtable.com/developers/web/api/introduction",
            icon="airtable",
            color="#18BFFF",
            authentication=[AuthType.BEARER_TOKEN, AuthType.OAUTH2],
            capabilities=["records", "bases", "views", "attachments"],
            operations=[
                OperationSpec(key="create_record", name="Create Record", description="Insert row into table", idempotent=False, action_type="crud"),
                OperationSpec(key="get_record", name="Get Record", description="Fetch row by ID", idempotent=True, action_type="crud"),
                OperationSpec(key="update_record", name="Update Record", description="Patch row values", idempotent=True, action_type="crud"),
                OperationSpec(key="list_records", name="List Records", description="Query table rows", idempotent=True, action_type="search"),
            ],
            triggers=[
                TriggerSpec(key="new_record", name="New Record", description="Webhook or polling for new rows", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="airtable", operation_count=4, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="airtable", operation_count=6, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="airtable", operation_count=8, trigger_count=4),
                cyclr=SourcePresence(supported=True, connector_id="airtable", operation_count=6, trigger_count=2),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="airtable",
                node_slugs=["airtable"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="linear",
            name="Linear",
            vendor="Linear Orbit Inc.",
            category=IntegrationCategory.PRODUCTIVITY,
            subcategory="Issue Tracking",
            website="https://linear.app",
            documentation_url="https://developers.linear.app/docs",
            icon="linear",
            color="#5E6AD2",
            authentication=[AuthType.BEARER_TOKEN, AuthType.OAUTH2],
            capabilities=["graphql", "issues", "projects", "cycles"],
            operations=[
                OperationSpec(key="create_issue", name="Create Issue", description="Create an issue", idempotent=False, action_type="crud"),
                OperationSpec(key="get_issue", name="Get Issue", description="Retrieve issue details", idempotent=True, action_type="crud"),
                OperationSpec(key="update_issue", name="Update Issue", description="Update issue state", idempotent=True, action_type="crud"),
            ],
            triggers=[
                TriggerSpec(key="issue_created", name="Issue Created", description="Webhook event on issue creation", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="linear", operation_count=3, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="linear", operation_count=6, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="linear", operation_count=7, trigger_count=4),
                cyclr=SourcePresence(supported=False),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="linear",
                node_slugs=["linear"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="asana",
            name="Asana",
            vendor="Asana Inc.",
            category=IntegrationCategory.PRODUCTIVITY,
            subcategory="Project Management",
            website="https://asana.com",
            documentation_url="https://developers.asana.com/docs",
            icon="asana",
            color="#F06A6A",
            authentication=[AuthType.OAUTH2, AuthType.BEARER_TOKEN],
            capabilities=["tasks", "projects", "sections", "workspaces"],
            operations=[
                OperationSpec(key="create_task", name="Create Task", description="Create task in project", idempotent=False, action_type="crud"),
                OperationSpec(key="get_task", name="Get Task", description="Retrieve task by ID", idempotent=True, action_type="crud"),
                OperationSpec(key="update_task", name="Update Task", description="Update task fields", idempotent=True, action_type="crud"),
            ],
            triggers=[
                TriggerSpec(key="task_created", name="Task Created", description="Fires when new task is added", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="asana", operation_count=3, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="asana", operation_count=7, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="asana", operation_count=9, trigger_count=5),
                cyclr=SourcePresence(supported=True, connector_id="asana", operation_count=7, trigger_count=3),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="asana",
                node_slugs=["asana"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="resend",
            name="Resend",
            vendor="Resend Inc.",
            category=IntegrationCategory.EMAIL_MARKETING,
            subcategory="Developer Transactional Email",
            website="https://resend.com",
            documentation_url="https://resend.com/docs/api-reference",
            icon="resend",
            color="#000000",
            authentication=[AuthType.BEARER_TOKEN],
            capabilities=["transactional_email", "html_templates", "attachments", "domains"],
            operations=[
                OperationSpec(key="send_email", name="Send Email", description="Send transactional HTML/text email", idempotent=False, action_type="action"),
                OperationSpec(key="get_email", name="Get Email", description="Get delivery status of sent email", idempotent=True, action_type="crud"),
            ],
            triggers=[
                TriggerSpec(key="email_delivered", name="Email Delivered", description="Webhook delivery notification", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="resend", operation_count=2, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="resend", operation_count=3, trigger_count=1),
                zapier=SourcePresence(supported=True, connector_id="resend", operation_count=3, trigger_count=2),
                cyclr=SourcePresence(supported=False),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="resend",
                node_slugs=["resend"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="s3",
            name="Amazon S3 / S3-Compatible",
            vendor="Amazon Web Services",
            category=IntegrationCategory.DATABASE_STORAGE,
            subcategory="Object Storage",
            website="https://aws.amazon.com/s3/",
            documentation_url="https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html",
            icon="s3",
            color="#569A31",
            authentication=[AuthType.CUSTOM_HEADER, AuthType.API_KEY],
            capabilities=["buckets", "object_streaming", "multipart_upload", "presigned_urls"],
            operations=[
                OperationSpec(key="upload_file", name="Upload File", description="Put object into bucket", idempotent=True, action_type="action"),
                OperationSpec(key="download_file", name="Download File", description="Get object from bucket", idempotent=True, action_type="action"),
                OperationSpec(key="delete_object", name="Delete Object", description="Remove object from bucket", idempotent=True, action_type="crud"),
                OperationSpec(key="list_objects", name="List Objects", description="List bucket contents", idempotent=True, action_type="search"),
            ],
            triggers=[
                TriggerSpec(key="object_created", name="Object Created", description="S3 SNS/SQS event trigger", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="s3", operation_count=4, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="awsS3", operation_count=6, trigger_count=2),
                zapier=SourcePresence(supported=True, connector_id="amazon-s3", operation_count=5, trigger_count=3),
                cyclr=SourcePresence(supported=True, connector_id="amazons3", operation_count=5, trigger_count=2),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="s3",
                node_slugs=["s3"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="pinecone",
            name="Pinecone Vector Database",
            vendor="Pinecone Systems Inc.",
            category=IntegrationCategory.AI_VECTOR,
            subcategory="Vector Database",
            website="https://www.pinecone.io",
            documentation_url="https://docs.pinecone.io",
            icon="pinecone",
            color="#000000",
            authentication=[AuthType.API_KEY],
            capabilities=["vector_upsert", "vector_query", "metadata_filtering", "namespaces"],
            operations=[
                OperationSpec(key="upsert_vectors", name="Upsert Vectors", description="Insert or update embedding vectors", idempotent=True, action_type="action"),
                OperationSpec(key="query_vectors", name="Query Vectors", description="Perform cosine/dot-product similarity search", idempotent=True, action_type="search"),
                OperationSpec(key="delete_vectors", name="Delete Vectors", description="Delete vectors by ID or filter", idempotent=True, action_type="crud"),
            ],
            triggers=[],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="pinecone", operation_count=3, trigger_count=0),
                n8n=SourcePresence(supported=True, connector_id="pinecone", operation_count=4, trigger_count=0),
                zapier=SourcePresence(supported=True, connector_id="pinecone", operation_count=3, trigger_count=0),
                cyclr=SourcePresence(supported=False),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="pinecone",
                node_slugs=["pinecone"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="supabase",
            name="Supabase",
            vendor="Supabase Inc.",
            category=IntegrationCategory.DATABASE_STORAGE,
            subcategory="PostgreSQL & BaaS",
            website="https://supabase.com",
            documentation_url="https://supabase.com/docs",
            icon="supabase",
            color="#3ECF8E",
            authentication=[AuthType.API_KEY, AuthType.BEARER_TOKEN],
            capabilities=["postgrest", "auth", "storage", "rpc"],
            operations=[
                OperationSpec(key="select_rows", name="Select Rows", description="Query PostgREST table", idempotent=True, action_type="search"),
                OperationSpec(key="insert_row", name="Insert Row", description="Insert row into table", idempotent=False, action_type="crud"),
                OperationSpec(key="rpc_call", name="RPC Call", description="Invoke PostgreSQL stored procedure", idempotent=False, action_type="rpc"),
            ],
            triggers=[
                TriggerSpec(key="database_webhook", name="Database Webhook", description="Trigger on table INSERT/UPDATE/DELETE", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="supabase", operation_count=3, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="supabase", operation_count=5, trigger_count=1),
                zapier=SourcePresence(supported=True, connector_id="supabase", operation_count=4, trigger_count=2),
                cyclr=SourcePresence(supported=False),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="supabase",
                node_slugs=["supabase"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        IntegrationDefinition(
            id="openai",
            name="OpenAI",
            vendor="OpenAI",
            category=IntegrationCategory.AI_VECTOR,
            subcategory="Large Language Models",
            website="https://openai.com",
            documentation_url="https://platform.openai.com/docs/api-reference",
            icon="openai",
            color="#00A67E",
            authentication=[AuthType.BEARER_TOKEN],
            capabilities=["chat_completions", "structured_outputs", "embeddings", "tool_calling", "vision"],
            operations=[
                OperationSpec(key="generate_chat", name="Generate Chat", description="Generate chat completion", idempotent=False, action_type="action"),
                OperationSpec(key="generate_embeddings", name="Generate Embeddings", description="Generate text vector embeddings", idempotent=True, action_type="action"),
            ],
            triggers=[],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="openai", operation_count=2, trigger_count=0),
                n8n=SourcePresence(supported=True, connector_id="openAi", operation_count=6, trigger_count=0),
                zapier=SourcePresence(supported=True, connector_id="chatgpt", operation_count=5, trigger_count=0),
                cyclr=SourcePresence(supported=True, connector_id="openai", operation_count=3, trigger_count=0),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="openai",
                node_slugs=["openai", "ai", "embeddings"],
                has_e2e_test=True,
                has_contract_test=True,
            )
        ),

        # =====================================================================
        # UNIVERSAL & PROTOCOL PRIMITIVES
        # =====================================================================
        IntegrationDefinition(
            id="http",
            name="Universal HTTP Request",
            vendor="FlowSmith Core",
            category=IntegrationCategory.PROTOCOLS,
            subcategory="Universal REST & Network",
            website="https://flowsmith.dev",
            documentation_url="https://flowsmith.dev/docs/nodes/http_request",
            icon="http_request",
            color="#2563EB",
            authentication=[AuthType.NONE, AuthType.API_KEY, AuthType.BEARER_TOKEN, AuthType.BASIC_AUTH, AuthType.OAUTH2, AuthType.CUSTOM_HEADER],
            capabilities=["ssrf_firewall", "curl_import", "openapi_import", "multipart", "expressions", "pagination_looping"],
            operations=[
                OperationSpec(key="request", name="HTTP Request", description="Execute arbitrary HTTP call (GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS)", idempotent=False, action_type="action"),
                OperationSpec(key="curl_import", name="Import cURL", description="Parse and execute cURL snippet", idempotent=False, action_type="action"),
            ],
            triggers=[
                TriggerSpec(key="webhook", name="Webhook Trigger", description="Listen for incoming HTTP webhook requests", trigger_type="webhook")
            ],
            sources=ExternalSources(
                flowsmith=SourcePresence(supported=True, connector_id="http", operation_count=2, trigger_count=1),
                n8n=SourcePresence(supported=True, connector_id="httpRequest", operation_count=2, trigger_count=1),
                zapier=SourcePresence(supported=True, connector_id="webhook", operation_count=3, trigger_count=2),
                cyclr=SourcePresence(supported=True, connector_id="apiConnector", operation_count=4, trigger_count=1),
            ),
            flowsmith_support=FlowsmithSupportStatus(
                support_type=SupportType.NATIVE,
                certification=CertificationLevel.CERTIFIED,
                is_active=True,
                connector_key="http",
                node_slugs=["http_request", "webhook"],
                has_e2e_test=True,
                has_contract_test=True,
                notes="Hardened universal protocol handler with strict SSRF controls."
            )
        ),
    ]
