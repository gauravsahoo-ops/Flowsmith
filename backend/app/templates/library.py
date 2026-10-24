"""Built-in workflow template catalog.

Single-operation connector templates cover the breadth of the integration
catalog. The curated business scenarios appended at the end of this module go
further: they combine native flow nodes (AI, filters, approvals, code) with one
or more real connector operations to model an end-to-end business process.
Every template still becomes fully runnable after the operator attaches
credentials and fills in the environment placeholders.
"""

from __future__ import annotations

import re
from typing import Any


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48]


def _template(
    name: str,
    description: str,
    category: str,
    node_type: str,
    operation: str,
    parameters: dict[str, Any],
    *,
    trigger: str = "manual_trigger",
    before: list[dict[str, Any]] | None = None,
    after: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a template whose primary connector action is wrapped by native steps.

    ``before`` runs between the trigger and the primary connector action.
    ``after`` runs after the action and before the result node. Steps use the
    same ``{id, type, name, parameters}`` shape as regular workflow nodes; the
    helper assigns positions and main-handle connections in sequence.
    """
    if trigger == "webhook":
        trigger_params = {
            "path": f"template-{_slug(name)}",
            "http_method": "POST",
        }
    elif trigger == "schedule":
        trigger_params = {"cron": "0 9 * * *", "timezone": "UTC"}
    else:
        trigger_params = {}
    chain = [
        {"id": "trigger", "type": trigger, "name": "Start", "parameters": trigger_params},
        *(before or []),
        {
            "id": "action",
            "type": node_type,
            "name": name,
            "parameters": {"operation": operation, **parameters},
        },
        *(after or []),
        {
            "id": "result",
            "type": "set_data",
            "name": "Return Result",
            "parameters": {"fields": {"ok": True, "result": "{{ $node.action.json }}"}},
        },
    ]
    node_ids = [node["id"] for node in chain]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError(f"Template {name!r} has duplicate node ids: {node_ids}")
    nodes = [
        {
            "id": node["id"],
            "type": node["type"],
            "name": node["name"],
            "position": {"x": 100 + 280 * index, "y": 200},
            "parameters": node.get("parameters", {}),
        }
        for index, node in enumerate(chain)
    ]
    connections = [
        {
            "source": chain[index]["id"],
            "sourceHandle": "main",
            "target": chain[index + 1]["id"],
            "targetHandle": "main",
        }
        for index in range(len(chain) - 1)
    ]
    return {
        "name": name,
        "description": description,
        "category": category,
        "workflow_data": {
            "name": name,
            "nodes": nodes,
            "connections": connections,
            "settings": {},
        },
    }


CONNECTOR_TEMPLATES: list[dict[str, Any]] = [
    _template(
        "Gmail Send Notification",
        "Send a formatted notification email through Gmail.",
        "communication", "gmail", "send",
        {"to": "{{ $env.GMAIL_TO }}", "subject": "Flowsmith notification",
         "body_text": "{{ $json.message }}"},
    ),
    _template(
        "Slack Post Alert",
        "Post an alert payload to a Slack channel.",
        "communication", "slack_api", "send_message",
        {"channel": "{{ $env.SLACK_CHANNEL }}", "text": "{{ $json.message }}"},
        trigger="webhook",
    ),
    _template(
        "HubSpot Create Contact",
        "Create or enrich a HubSpot contact from a webhook payload.",
        "crm", "hubspot", "create",
        {"object_type": "contacts", "properties": {
            "email": "{{ $json.email }}", "firstname": "{{ $json.first_name }}",
        }},
        trigger="webhook",
    ),
    _template(
        "Salesforce Create Lead",
        "Create a Salesforce Lead from an inbound lead payload.",
        "crm", "salesforce", "create",
        {"object_name": "Lead", "record": {
            "LastName": "{{ $json.last_name }}", "Company": "{{ $json.company }}",
            "Email": "{{ $json.email }}",
        }},
        trigger="webhook",
    ),
    _template(
        "Jira Create Issue",
        "Open a Jira issue from a scheduled or manual event.",
        "devops", "jira", "create_issue",
        {"project_key": "{{ $env.JIRA_PROJECT_KEY }}", "summary": "{{ $json.summary }}"},
    ),
    _template(
        "GitHub Open Issue",
        "Create a GitHub issue from an alert or webhook.",
        "devops", "github", "create_issue",
        {"owner": "{{ $env.GITHUB_OWNER }}", "repo": "{{ $env.GITHUB_REPO }}",
         "title": "{{ $json.title }}", "body": "{{ $json.body }}"},
        trigger="webhook",
    ),
    _template(
        "Notion Create Database Page",
        "Add a structured page to a Notion database.",
        "productivity", "notion", "create_page",
        {"database_id": "{{ $env.NOTION_DATABASE_ID }}", "properties": {
            "Name": {"title": [{"text": {"content": "{{ $json.name }}"}}]},
        }},
    ),
    _template(
        "Airtable Create Record",
        "Insert a record into an Airtable table.",
        "productivity", "airtable", "create_record",
        {"base_id": "{{ $env.AIRTABLE_BASE_ID }}", "table_name": "Contacts",
         "fields": {"Name": "{{ $json.name }}", "Email": "{{ $json.email }}"}},
    ),
    _template(
        "Asana Create Task",
        "Create an Asana task from a project event.",
        "productivity", "asana", "create_task",
        {"project_id": "{{ $env.ASANA_PROJECT_ID }}", "name": "{{ $json.name }}"},
    ),
    _template(
        "Trello Create Card",
        "Add a card to a Trello list.",
        "productivity", "trello", "create_card",
        {"list_id": "{{ $env.TRELLO_LIST_ID }}", "name": "{{ $json.name }}"},
    ),
    _template(
        "Monday.com Create Item",
        "Add an item to a Monday.com board.",
        "productivity", "monday", "create_item",
        {"board_id": "{{ $env.MONDAY_BOARD_ID }}", "item_name": "{{ $json.name }}"},
    ),
    _template(
        "ClickUp Create Task",
        "Create a ClickUp task from an inbound request.",
        "productivity", "clickup", "create_task",
        {"list_id": "{{ $env.CLICKUP_LIST_ID }}", "name": "{{ $json.name }}"},
    ),
    _template(
        "Pipedrive Create Deal",
        "Create a Pipedrive deal from a lead payload.",
        "crm", "pipedrive", "create_deal",
        {"title": "{{ $json.title }}", "value": 1000, "currency": "USD"},
    ),
    _template(
        "Zendesk Create Ticket",
        "Create a Zendesk support ticket from a webhook.",
        "support", "zendesk", "create_ticket",
        {"subject": "{{ $json.subject }}", "comment": {"body": "{{ $json.message }}"}},
        trigger="webhook",
    ),
    _template(
        "Freshdesk Create Ticket",
        "Create a Freshdesk ticket from a support email payload.",
        "support", "freshdesk", "create_ticket",
        {"subject": "{{ $json.subject }}", "description": "{{ $json.message }}",
         "email": "{{ $json.email }}"},
        trigger="webhook",
    ),
    _template(
        "Intercom Reply to Conversation",
        "Reply to an Intercom conversation from an automation event.",
        "support", "intercom", "reply_conversation",
        {"conversation_id": "{{ $env.INTERCOM_CONVERSATION_ID }}",
         "body_text": "{{ $json.message }}"},
    ),
    _template(
        "Shopify Create Product",
        "Create a Shopify product from a catalog payload.",
        "commerce", "shopify", "create_product",
        {"title": "{{ $json.title }}", "body_html": "{{ $json.description }}"},
    ),
    _template(
        "Stripe Create Customer",
        "Create a Stripe customer from a signup event.",
        "finance", "stripe", "create_customer",
        {"email": "{{ $json.email }}", "name": "{{ $json.name }}"},
    ),
    _template(
        "QuickBooks Create Customer",
        "Create a QuickBooks customer record.",
        "finance", "quickbooks", "create_customer",
        {"display_name": "{{ $json.name }}", "email": "{{ $json.email }}"},
    ),
    _template(
        "Xero Create Invoice",
        "Create a Xero invoice with one line item.",
        "finance", "xero", "create_invoice",
        {"contact_id": "{{ $env.XERO_CONTACT_ID }}", "line_items": [{
            "Description": "{{ $json.description }}", "Quantity": 1, "UnitAmount": 100,
        }]},
    ),
    _template(
        "DocuSign Create Envelope",
        "Send a document for signature through DocuSign.",
        "productivity", "docusign", "create_envelope",
        {"email_subject": "Please sign {{ $json.document_name }}", "recipients": [{
            "email": "{{ $json.signer_email }}", "name": "{{ $json.signer_name }}",
            "recipient_id": "1", "routing_order": "1",
        }]},
    ),
    _template(
        "SendGrid Send Email",
        "Send a transactional email through SendGrid.",
        "communication", "sendgrid", "send_mail",
        {"to_email": "{{ $json.email }}", "from_email": "{{ $env.SENDGRID_FROM }}",
         "subject": "Welcome", "content": "Hello {{ $json.name }}"},
    ),
    _template(
        "Resend Send Email",
        "Send a transactional email through Resend.",
        "communication", "resend", "send_email",
        {"from": "{{ $env.RESEND_FROM }}", "to": "{{ $json.email }}",
         "subject": "Welcome", "text": "Hello {{ $json.name }}"},
    ),
    _template(
        "Brevo Send Email",
        "Send a transactional email through Brevo.",
        "communication", "brevo", "send_email",
        {"sender": {"email": "{{ $env.BREVO_FROM }}", "name": "Flowsmith"},
         "to": [{"email": "{{ $json.email }}"}], "subject": "Welcome"},
    ),
    _template(
        "Mailchimp Add List Member",
        "Add a subscriber to a Mailchimp audience.",
        "marketing", "mailchimp", "add_member",
        {"list_id": "{{ $env.MAILCHIMP_LIST_ID }}", "email": "{{ $json.email }}"},
    ),
    _template(
        "Google Sheets Append Row",
        "Append a row to a Google Sheets spreadsheet.",
        "data", "google_sheets", "append",
        {"spreadsheet_id": "{{ $env.GOOGLE_SHEET_ID }}", "values": [[
            "{{ $json.name }}", "{{ $json.email }}",
        ]]},
    ),
    _template(
        "Google Drive Upload File",
        "Upload a generated document to Google Drive.",
        "storage", "google_drive", "upload_file",
        {"name": "{{ $json.file_name }}", "content": "{{ $json.content }}"},
    ),
    _template(
        "Google Docs Create Document",
        "Create a Google Doc from a title and body.",
        "productivity", "google_docs", "create_document",
        {"title": "{{ $json.title }}"},
    ),
    _template(
        "Google Calendar Create Event",
        "Create a calendar event from a scheduling payload.",
        "productivity", "google_calendar", "create_event",
        {"event": {"summary": "{{ $json.title }}",
                   "start": {"dateTime": "{{ $json.start }}"},
                   "end": {"dateTime": "{{ $json.end }}"}}},
    ),
    _template(
        "Outlook Send Email",
        "Send an email through Microsoft Outlook.",
        "communication", "outlook", "send",
        {"to": "{{ $json.email }}", "subject": "Welcome",
         "body": "Hello {{ $json.name }}"},
    ),
    _template(
        "Microsoft Teams Send Message",
        "Post a message to a Microsoft Teams channel.",
        "communication", "msteams", "send_message",
        {"team_id": "{{ $env.TEAMS_TEAM_ID }}", "channel_id": "{{ $env.TEAMS_CHANNEL_ID }}",
         "content": "{{ $json.message }}"},
        trigger="webhook",
    ),
    _template(
        "Discord Send Message",
        "Post a notification to a Discord channel.",
        "communication", "discord", "send_message",
        {"channel_id": "{{ $env.DISCORD_CHANNEL_ID }}", "content": "{{ $json.message }}"},
    ),
    _template(
        "Zoom Create Meeting",
        "Create a Zoom meeting from a scheduling request.",
        "productivity", "zoom", "create_meeting",
        {"topic": "{{ $json.topic }}", "duration_min": 30},
    ),
    _template(
        "Calendly Create Scheduling Link",
        "Generate a Calendly scheduling link.",
        "productivity", "calendly", "create_scheduling_link",
        {"owner_uri": "{{ $env.CALENDLY_OWNER_URI }}"},
    ),
    _template(
        "Typeform Fetch Responses",
        "Fetch recent Typeform responses for processing.",
        "data", "typeform", "get_responses",
        {"form_id": "{{ $env.TYPEFORM_FORM_ID }}"},
        trigger="schedule",
    ),
    _template(
        "Dropbox List Folder",
        "List files in a Dropbox folder for downstream processing.",
        "storage", "dropbox", "list_folder",
        {"path": "{{ $env.DROPBOX_PATH }}"},
        trigger="schedule",
    ),
    _template(
        "Box Create Folder",
        "Create a Box folder for a new customer or project.",
        "storage", "box", "create_folder",
        {"name": "{{ $json.folder_name }}", "parent_id": "{{ $env.BOX_PARENT_ID }}"},
    ),
    _template(
        "S3 Upload File",
        "Upload a generated artifact to S3 or an S3-compatible store.",
        "storage", "s3", "upload_file",
        {"key": "uploads/{{ $json.file_name }}", "content": "{{ $json.content }}"},
    ),
    _template(
        "PostgreSQL Query",
        "Run a PostgreSQL query and return the rows.",
        "data", "postgres", "query",
        {"sql": "SELECT 1 AS ok"},
        trigger="manual_trigger",
    ),
    _template(
        "MySQL Query",
        "Run a MySQL query and return the rows.",
        "data", "mysql", "query",
        {"sql": "SELECT 1 AS ok"},
        trigger="manual_trigger",
    ),
    _template(
        "BigQuery Run Query",
        "Run a Google BigQuery SQL query.",
        "data", "bigquery", "query",
        {"query": "SELECT 1 AS ok"},
        trigger="schedule",
    ),
    _template(
        "Snowflake Execute Query",
        "Execute a Snowflake SQL statement.",
        "data", "snowflake", "execute_query",
        {"statement": "SELECT 1 AS ok"},
        trigger="schedule",
    ),
    _template(
        "Supabase Insert Row",
        "Insert a row into a Supabase table.",
        "data", "supabase", "insert_row",
        {"table": "events", "data": {"name": "{{ $json.name }}"}},
    ),
    _template(
        "OpenAI Create Embedding",
        "Create an OpenAI embedding for semantic search.",
        "ai", "openai", "create_embedding",
        {"model": "text-embedding-3-small", "text": "{{ $json.text }}"},
    ),
    _template(
        "Anthropic Generate Message",
        "Generate an Anthropic Claude response from a prompt.",
        "ai", "anthropic", "generate_message",
        {"prompt": "{{ $json.prompt }}"},
    ),
    _template(
        "Pinecone Query Vectors",
        "Search a Pinecone index for nearest vectors.",
        "ai", "pinecone", "query_vectors",
        {"vector": [0.1, 0.2, 0.3], "top_k": 5},
    ),
    _template(
        "Twilio Send SMS",
        "Send an SMS notification through Twilio.",
        "communication", "twilio", "send_sms",
        {"from_number": "{{ $env.TWILIO_FROM }}", "to_number": "{{ $json.phone }}",
         "body": "{{ $json.message }}"},
    ),
    _template(
        "WhatsApp Send Text",
        "Send a WhatsApp text message through the Cloud API.",
        "communication", "whatsapp", "send_text",
        {"to": "{{ $json.phone }}", "body": "{{ $json.message }}"},
    ),
    _template(
        "PagerDuty Create Incident",
        "Create a PagerDuty incident from an alert.",
        "devops", "pagerduty", "create_incident",
        {"title": "{{ $json.title }}", "service_id": "{{ $env.PAGERDUTY_SERVICE_ID }}"},
        trigger="webhook",
    ),
    _template(
        "Sentry List Issues",
        "List recent Sentry issues for triage.",
        "devops", "sentry", "list_issues",
        {"organization_slug": "{{ $env.SENTRY_ORG }}", "project_slug": "{{ $env.SENTRY_PROJECT }}"},
        trigger="schedule",
    ),
    _template(
        "GitLab Create Issue",
        "Create a GitLab issue from a pipeline or alert.",
        "devops", "gitlab", "create_issue",
        {"project_id": "{{ $env.GITLAB_PROJECT_ID }}", "title": "{{ $json.title }}"},
    ),
    _template(
        "Bitbucket Create Pull Request",
        "Open a Bitbucket pull request from a feature branch.",
        "devops", "bitbucket", "create_pull_request",
        {"workspace": "{{ $env.BITBUCKET_WORKSPACE }}", "repo_slug": "{{ $env.BITBUCKET_REPO }}",
         "title": "{{ $json.title }}", "source_branch": "{{ $json.branch }}",
         "destination_branch": "main"},
    ),
    _template(
        "Linear Create Issue",
        "Create a Linear issue from a product or support event.",
        "productivity", "linear", "create_issue",
        {"team_id": "{{ $env.LINEAR_TEAM_ID }}", "title": "{{ $json.title }}"},
    ),
    _template(
        "Zoho CRM Create Record",
        "Create a Zoho CRM lead record.",
        "crm", "zoho_crm", "create_records",
        {"module": "Leads", "data": [{
            "Last_Name": "{{ $json.last_name }}", "Email": "{{ $json.email }}",
        }]},
    ),
    _template(
        "ActiveCampaign Create Contact",
        "Create an ActiveCampaign contact from a signup.",
        "marketing", "activecampaign", "create_contact",
        {"email": "{{ $json.email }}", "first_name": "{{ $json.first_name }}"},
    ),
    _template(
        "ServiceNow Create Incident",
        "Create a ServiceNow incident from an alert.",
        "support", "servicenow", "create_record",
        {"table": "incident", "fields": {
            "short_description": "{{ $json.summary }}",
            "description": "{{ $json.description }}",
        }},
        trigger="webhook",
    ),
    _template(
        "Gmail Search Unread",
        "Search unread Gmail messages for an automation run.",
        "communication", "gmail", "list_messages",
        {"query": "is:unread", "max_results": 20},
        trigger="schedule",
    ),
    _template(
        "Slack List Channels",
        "List Slack channels for a provisioning or audit workflow.",
        "communication", "slack_api", "list_channels",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "HubSpot List Contacts",
        "List HubSpot contacts for enrichment or reporting.",
        "crm", "hubspot", "list",
        {"object_type": "contacts", "limit": 100},
        trigger="schedule",
    ),
    _template(
        "Salesforce Search Leads",
        "Search Salesforce Leads by email from a webhook payload.",
        "crm", "salesforce", "search",
        {"object_name": "Lead", "search_field": "Email",
         "search_value": "{{ $json.email }}"},
        trigger="webhook",
    ),
    _template(
        "Jira Search Issues",
        "Search Jira issues with JQL for a scheduled report.",
        "devops", "jira", "search",
        {"jql": "project = {{ $env.JIRA_PROJECT_KEY }} ORDER BY updated DESC"},
        trigger="schedule",
    ),
    _template(
        "GitHub List Issues",
        "List open GitHub issues for triage or reporting.",
        "devops", "github", "list_issues",
        {"owner": "{{ $env.GITHUB_OWNER }}", "repo": "{{ $env.GITHUB_REPO }}",
         "state": "open", "per_page": 50},
        trigger="schedule",
    ),
    _template(
        "Notion Query Database",
        "Query a Notion database for recently updated records.",
        "productivity", "notion", "query_database",
        {"database_id": "{{ $env.NOTION_DATABASE_ID }}", "page_size": 50},
        trigger="schedule",
    ),
    _template(
        "Airtable List Records",
        "List Airtable records for a sync or audit workflow.",
        "productivity", "airtable", "list_records",
        {"base_id": "{{ $env.AIRTABLE_BASE_ID }}", "table_name": "Contacts",
         "page_size": 100},
        trigger="schedule",
    ),
    _template(
        "Asana List Tasks",
        "List tasks in an Asana project.",
        "productivity", "asana", "list_tasks",
        {"project_id": "{{ $env.ASANA_PROJECT_ID }}"},
        trigger="schedule",
    ),
    _template(
        "Trello List Cards",
        "List cards on a Trello board.",
        "productivity", "trello", "list_cards",
        {"board_id": "{{ $env.TRELLO_BOARD_ID }}"},
        trigger="schedule",
    ),
    _template(
        "Monday List Board Items",
        "List items from a Monday.com board.",
        "productivity", "monday", "list_items",
        {"board_id": "{{ $env.MONDAY_BOARD_ID }}", "limit": 100},
        trigger="schedule",
    ),
    _template(
        "ClickUp List Tasks",
        "List tasks in a ClickUp list.",
        "productivity", "clickup", "list_tasks",
        {"list_id": "{{ $env.CLICKUP_LIST_ID }}", "limit": 100},
        trigger="schedule",
    ),
    _template(
        "Pipedrive List Deals",
        "List Pipedrive deals for a revenue report.",
        "crm", "pipedrive", "list_deals",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "Zendesk List Tickets",
        "List Zendesk tickets for support operations.",
        "support", "zendesk", "list_tickets",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "Freshdesk List Tickets",
        "List Freshdesk tickets for support operations.",
        "support", "freshdesk", "list_tickets",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "Intercom List Conversations",
        "List recent Intercom conversations for triage.",
        "support", "intercom", "list_conversations",
        {"per_page": 50},
        trigger="schedule",
    ),
    _template(
        "Shopify List Products",
        "List Shopify products for catalog synchronization.",
        "commerce", "shopify", "list_products",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "Stripe List Customers",
        "List Stripe customers for a billing report.",
        "finance", "stripe", "list_customers",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "QuickBooks List Customers",
        "List QuickBooks customers for accounting sync.",
        "finance", "quickbooks", "list_customers",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "Xero List Invoices",
        "List Xero invoices for a finance report.",
        "finance", "xero", "list_invoices",
        {"page": 1},
        trigger="schedule",
    ),
    _template(
        "DocuSign List Envelopes",
        "List DocuSign envelopes updated since a given date.",
        "productivity", "docusign", "list_envelopes",
        {"from_date": "2026-01-01", "count": 100},
        trigger="schedule",
    ),
    _template(
        "SendGrid List Templates",
        "List SendGrid email templates for a sync job.",
        "communication", "sendgrid", "list_templates",
        {"generations": "dynamic"},
        trigger="schedule",
    ),
    _template(
        "Resend List Emails",
        "List recent Resend emails for delivery monitoring.",
        "communication", "resend", "list_emails",
        {},
        trigger="schedule",
    ),
    _template(
        "Brevo List Contacts",
        "List Brevo contacts for a marketing sync.",
        "marketing", "brevo", "list_contacts",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "Mailchimp List Audiences",
        "List Mailchimp audiences for a marketing report.",
        "marketing", "mailchimp", "list_lists",
        {"limit": 100},
        trigger="schedule",
    ),
    _template(
        "Google Sheets Read Range",
        "Read a range from Google Sheets for processing.",
        "data", "google_sheets", "read",
        {"spreadsheet_id": "{{ $env.GOOGLE_SHEET_ID }}", "range": "Sheet1!A1:Z100"},
        trigger="schedule",
    ),
    _template(
        "Google Drive List Files",
        "List files in a Google Drive folder.",
        "storage", "google_drive", "list_files",
        {"folder_id": "{{ $env.GOOGLE_DRIVE_FOLDER_ID }}", "page_size": 100},
        trigger="schedule",
    ),
    _template(
        "Google Docs Get Document",
        "Fetch a Google Doc for summarization or archival.",
        "productivity", "google_docs", "get_document",
        {"document_id": "{{ $env.GOOGLE_DOC_ID }}"},
    ),
    _template(
        "Google Calendar List Events",
        "List upcoming Google Calendar events.",
        "productivity", "google_calendar", "list_events",
        {"max_results": 50},
        trigger="schedule",
    ),
    _template(
        "Outlook List Messages",
        "List Outlook inbox messages for processing.",
        "communication", "outlook", "list_messages",
        {"folder": "inbox", "top": 50},
        trigger="schedule",
    ),
    _template(
        "Microsoft Teams List Teams",
        "List Microsoft Teams teams for provisioning.",
        "communication", "msteams", "list_teams",
        {},
        trigger="schedule",
    ),
    _template(
        "Discord List Channels",
        "List channels in a Discord guild.",
        "communication", "discord", "list_channels",
        {"guild_id": "{{ $env.DISCORD_GUILD_ID }}"},
        trigger="schedule",
    ),
    _template(
        "Zoom List Meetings",
        "List upcoming Zoom meetings for a report.",
        "productivity", "zoom", "list_meetings",
        {"user_id": "me"},
        trigger="schedule",
    ),
    _template(
        "Calendly List Events",
        "List Calendly scheduled events.",
        "productivity", "calendly", "list_events",
        {"count": 100},
        trigger="schedule",
    ),
    _template(
        "Typeform List Forms",
        "List Typeform forms for a reporting workflow.",
        "data", "typeform", "list_forms",
        {"page_size": 100},
        trigger="schedule",
    ),
    _template(
        "Dropbox Search Files",
        "Search Dropbox for files matching a webhook query.",
        "storage", "dropbox", "search",
        {"query": "{{ $json.query }}", "limit": 100},
        trigger="webhook",
    ),
]


# Curated, multi-step business scenarios. Each one combines native flow nodes
# (AI, filters, approvals, code) with real connector operations; the graph and
# operation keys are exercised by tests/test_template_catalog.py.
CURATED_BUSINESS_TEMPLATES: list[dict[str, Any]] = [
    # --- Support operations -------------------------------------------------
    _template(
        "Zendesk Priority Triage with AI Summary",
        "Classify each inbound support request with AI, open a Zendesk ticket at the suggested priority, and alert the support channel with the triage summary.",
        "support", "zendesk", "create_ticket",
        {
            "subject": "{{ $node.trigger.json.subject }}",
            "comment": "{{ $node.trigger.json.message }}",
            "priority": "{{ $json.response.priority }}",
        },
        trigger="webhook",
        before=[{
            "id": "triage",
            "type": "ai",
            "name": "Classify Ticket Urgency",
            "parameters": {
                "system_message": "You are a support operations classifier. Return JSON with priority (low, normal, high, or urgent), sentiment, and summary.",
                "prompt": "Classify this inbound support request.\nSubject: {{ $json.subject }}\nMessage: {{ $json.message }}",
                "response_format": "json",
                "temperature": 0.1,
            },
        }],
        after=[{
            "id": "notify",
            "type": "slack_api",
            "name": "Alert Support Channel",
            "parameters": {
                "operation": "send_message",
                "channel": "{{ $env.SUPPORT_TRIAGE_CHANNEL }}",
                "text": "New Zendesk ticket: {{ $node.trigger.json.subject }} (priority {{ $node.triage.json.response.priority }})",
            },
        }],
    ),
    _template(
        "Freshdesk SLA Breach Escalation Sweep",
        "Scan Freshdesk for tickets escalated by an SLA breach, raise their priority to urgent, and notify both the support manager and the response channel.",
        "support", "freshdesk", "update_ticket",
        {"ticket_id": "{{ $json.id }}", "status": 2, "priority": 4},
        trigger="schedule",
        before=[
            {
                "id": "fetch_tickets",
                "type": "freshdesk",
                "name": "List Freshdesk Tickets",
                "parameters": {"operation": "list_tickets", "limit": 100},
            },
            {
                "id": "ticket_items",
                "type": "split",
                "name": "Split Ticket List",
                "parameters": {"field": "tickets"},
            },
            {
                "id": "sla_filter",
                "type": "filter",
                "name": "Only Breached Tickets",
                "parameters": {
                    "conditions": [{
                        "id": "escalated",
                        "left": "{{ $json.is_escalated }}",
                        "operator": "is true",
                        "right": True,
                        "combinator": "AND",
                    }],
                },
            },
        ],
        after=[
            {
                "id": "manager_email",
                "type": "gmail",
                "name": "Email Support Manager",
                "parameters": {
                    "operation": "send",
                    "to": "{{ $env.SUPPORT_MANAGER_EMAIL }}",
                    "subject": "Freshdesk SLA breach escalated",
                    "body_text": "Ticket {{ $node.action.json.id }} has breached its SLA and was raised to urgent.",
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Alert Response Channel",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.SUPPORT_ALERT_CHANNEL }}",
                    "text": "Freshdesk SLA breach escalated for ticket {{ $node.action.json.id }}.",
                },
            },
        ],
    ),
    _template(
        "Intercom At-Risk Conversation Digest",
        "Review recent Intercom conversations with AI to surface churn risk, then post a prioritized digest to the customer success channel.",
        "support", "intercom", "list_conversations",
        {"per_page": 50},
        trigger="schedule",
        after=[
            {
                "id": "risk_review",
                "type": "ai",
                "name": "Identify At-Risk Conversations",
                "parameters": {
                    "system_message": "You are a customer success analyst. Be concise and cite the customer signal behind each risk.",
                    "prompt": "Review these Intercom conversations. List accounts showing churn risk, the reason, and a recommended next step.\n{{ JSON.stringify($json) }}",
                    "temperature": 0.2,
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Post Customer Success Digest",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.CUSTOMER_SUCCESS_CHANNEL }}",
                    "text": "At-risk conversations from Intercom:\n{{ $json.response }}",
                },
            },
        ],
    ),
    _template(
        "ServiceNow Major Incident Bridge",
        "Open a Sev-1 ServiceNow incident, spin up the incident Slack bridge, and page the on-call service owner from one webhook.",
        "support", "servicenow", "create_record",
        {
            "table": "incident",
            "fields": {
                "short_description": "{{ $json.summary }}",
                "description": "{{ $json.details }}",
                "impact": "1",
                "urgency": "1",
            },
        },
        trigger="webhook",
        after=[
            {
                "id": "bridge",
                "type": "slack_api",
                "name": "Open Incident Bridge",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.INCIDENT_BRIDGE_CHANNEL }}",
                    "text": "Major incident opened: {{ $node.action.json.result.number }} — {{ $node.trigger.json.summary }}",
                },
            },
            {
                "id": "page_oncall",
                "type": "pagerduty",
                "name": "Page Service Owner",
                "parameters": {
                    "operation": "create_incident",
                    "title": "Major incident {{ $node.action.json.result.number }}: {{ $node.trigger.json.summary }}",
                    "service_id": "{{ $env.PAGERDUTY_SERVICE_ID }}",
                    "urgency": "high",
                    "description": "{{ $node.trigger.json.details }}",
                },
            },
        ],
    ),

    # --- Sales and CRM ------------------------------------------------------
    _template(
        "HubSpot Inbound Lead Qualification",
        "Validate an inbound lead, create the HubSpot contact, score fit with AI, and hand the qualified lead to the sales channel.",
        "crm", "hubspot", "create",
        {
            "object_type": "contacts",
            "properties": {
                "email": "{{ $json.email }}",
                "firstname": "{{ $json.first_name }}",
                "lastname": "{{ $json.last_name }}",
                "lifecyclestage": "lead",
            },
        },
        trigger="webhook",
        before=[{
            "id": "email_filter",
            "type": "filter",
            "name": "Require Business Email",
            "parameters": {
                "conditions": [{
                    "id": "email_present",
                    "left": "{{ $json.email }}",
                    "operator": "is not empty",
                    "right": "",
                    "combinator": "AND",
                }],
            },
        }],
        after=[
            {
                "id": "score",
                "type": "ai",
                "name": "Score Lead Fit",
                "parameters": {
                    "system_message": "You are a B2B sales researcher. Return JSON with score (0-100), segment, and one suggested opening line.",
                    "prompt": "Score this inbound lead for fit with an enterprise workflow automation product.\n{{ JSON.stringify($node.action.json) }}",
                    "response_format": "json",
                    "temperature": 0.2,
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Hand Off to Sales",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.SALES_LEADS_CHANNEL }}",
                    "text": "New HubSpot lead {{ $node.trigger.json.email }} scored by AI:\n{{ JSON.stringify($json.response) }}",
                },
            },
        ],
    ),
    _template(
        "Salesforce Stale Pipeline Nudge",
        "Query opportunities with no recent activity, ask AI to draft owner-specific nudges, and email the sales operations team a concise pipeline review.",
        "crm", "salesforce", "query",
        {
            "soql": (
                "SELECT Id, Name, StageName, Amount, Owner.Email, LastActivityDate "
                "FROM Opportunity WHERE IsClosed = false AND LastActivityDate < LAST_N_DAYS:30 "
                "ORDER BY Amount DESC"
            ),
        },
        trigger="schedule",
        after=[
            {
                "id": "draft",
                "type": "ai",
                "name": "Draft Pipeline Nudges",
                "parameters": {
                    "system_message": "You are a sales operations lead. Group stale opportunities by owner and write one short, specific nudge per owner.",
                    "prompt": "Draft follow-up nudges for these stale Salesforce opportunities.\n{{ JSON.stringify($json) }}",
                    "temperature": 0.3,
                },
            },
            {
                "id": "email",
                "type": "gmail",
                "name": "Email Pipeline Review",
                "parameters": {
                    "operation": "send",
                    "to": "{{ $env.SALES_OPERATIONS_EMAIL }}",
                    "subject": "Stale Salesforce opportunities need attention",
                    "body_text": "{{ $json.response }}",
                },
            },
        ],
    ),
    _template(
        "Pipedrive Post-Demo Follow-Up",
        "Log a demo recap on the Pipedrive deal, send the attendee a next-step email, and post a handoff note to the sales channel.",
        "crm", "pipedrive", "add_note",
        {
            "deal_id": "{{ $json.deal_id }}",
            "content": "Demo completed. Recap sent to {{ $json.attendee_email }}. Next step: {{ $json.next_step }}",
        },
        trigger="webhook",
        after=[
            {
                "id": "recap_email",
                "type": "gmail",
                "name": "Send Demo Recap",
                "parameters": {
                    "operation": "send",
                    "to": "{{ $node.trigger.json.attendee_email }}",
                    "subject": "Your demo recap and next steps",
                    "body_text": (
                        "Hi {{ $node.trigger.json.attendee_name }},\n\n"
                        "Thanks for your time today. Our agreed next step is "
                        "{{ $node.trigger.json.next_step }}.\n\nFlowsmith"
                    ),
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify Sales Channel",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.SALES_ACTIVITY_CHANNEL }}",
                    "text": "Post-demo follow-up sent for Pipedrive deal {{ $node.trigger.json.deal_id }}.",
                },
            },
        ],
    ),
    _template(
        "Zoho CRM Webinar Lead Assignment",
        "Filter opt-in webinar attendees, create Zoho CRM leads with source attribution, and notify the sales team in Slack.",
        "crm", "zoho_crm", "create_records",
        {
            "module": "Leads",
            "data": [{
                "Last_Name": "{{ $json.last_name }}",
                "Email": "{{ $json.email }}",
                "Company": "{{ $json.company }}",
                "Lead_Source": "Webinar",
            }],
        },
        trigger="webhook",
        before=[{
            "id": "opt_in",
            "type": "filter",
            "name": "Only Opted-In Attendees",
            "parameters": {
                "conditions": [{
                    "id": "opt_in",
                    "left": "{{ $json.opt_in }}",
                    "operator": "is true",
                    "right": True,
                    "combinator": "AND",
                }],
            },
        }],
        after=[{
            "id": "notify",
            "type": "slack_api",
            "name": "Notify Webinar Sales Team",
            "parameters": {
                "operation": "send_message",
                "channel": "{{ $env.SALES_LEADS_CHANNEL }}",
                "text": "Webinar lead assigned in Zoho CRM: {{ $node.trigger.json.email }}",
            },
        }],
    ),

    # --- Finance and accounting --------------------------------------------
    _template(
        "Stripe Payment Reconciliation Log",
        "Pull recent Stripe payment intents and append the payment status to a reconciliation sheet for the finance close.",
        "finance", "stripe", "list_payment_intents",
        {"limit": 100},
        trigger="schedule",
        after=[
            {
                "id": "payment_items",
                "type": "split",
                "name": "Split Payment Intents",
                "parameters": {"field": "payment_intents"},
            },
            {
                "id": "sheet",
                "type": "google_sheets",
                "name": "Append Reconciliation Row",
                "parameters": {
                    "operation": "append",
                    "spreadsheet_id": "{{ $env.FINANCE_SHEET_ID }}",
                    "range": "Stripe Reconciliation!A:E",
                    "values": [
                        "{{ $json.id }}", "{{ $json.amount }}", "{{ $json.currency }}",
                        "{{ $json.status }}", "{{ $json.created }}",
                    ],
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify Finance Channel",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.FINANCE_CHANNEL }}",
                    "text": "Stripe payment intents synced to the reconciliation sheet.",
                },
            },
        ],
    ),
    _template(
        "QuickBooks Open Invoice Collections Digest",
        "Query open QuickBooks invoices, keep positive balances, and email accounts receivable a bundled collections summary.",
        "finance", "quickbooks", "query",
        {"query": "SELECT Id, DocNumber, DueDate, Balance, CustomerRef FROM Invoice WHERE Balance > '0'"},
        trigger="schedule",
        after=[
            {
                "id": "invoice_items",
                "type": "split",
                "name": "Split Invoice List",
                "parameters": {"field": "QueryResponse.Invoice"},
            },
            {
                "id": "balance_filter",
                "type": "filter",
                "name": "Keep Positive Balances",
                "parameters": {
                    "conditions": [{
                        "id": "balance",
                        "left": "{{ $json.Balance }}",
                        "operator": "is greater than",
                        "right": 0,
                        "combinator": "AND",
                    }],
                    "convertTypes": True,
                },
            },
            {
                "id": "bundle",
                "type": "aggregate",
                "name": "Bundle Invoice Summary",
                "parameters": {"field": "invoices"},
            },
            {
                "id": "email",
                "type": "gmail",
                "name": "Email Collections Summary",
                "parameters": {
                    "operation": "send",
                    "to": "{{ $env.ACCOUNTS_RECEIVABLE_EMAIL }}",
                    "subject": "Open QuickBooks invoices",
                    "body_text": "Open invoice summary:\n{{ JSON.stringify($json.invoices) }}",
                },
            },
        ],
    ),
    _template(
        "Xero Overdue Invoice Escalation",
        "List authorised Xero invoices with an outstanding balance, isolate past-due items, and alert the finance channel for follow-up.",
        "finance", "xero", "list_invoices",
        {"where": 'Status=="AUTHORISED" AND AmountDue > 0', "page": 1},
        trigger="schedule",
        after=[
            {
                "id": "invoice_items",
                "type": "split",
                "name": "Split Xero Invoices",
                "parameters": {"field": "Invoices"},
            },
            {
                "id": "overdue",
                "type": "filter",
                "name": "Past Due Invoices",
                "parameters": {
                    "conditions": [{
                        "id": "past_due",
                        "left": "{{ $json.DueDateString }}",
                        "operator": "is before",
                        "right": "{{ $now }}",
                        "combinator": "AND",
                    }],
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Alert Accounts Receivable",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.FINANCE_CHANNEL }}",
                    "text": "Xero reports overdue invoices with an outstanding balance. Review the AR queue.",
                },
            },
        ],
    ),
    _template(
        "Stripe Failed Payment Dunning",
        "Filter failed Stripe payment events, fetch the payment intent, send a Resend dunning email, and notify the billing channel.",
        "finance", "stripe", "get_payment_intent",
        {"payment_intent_id": "{{ $json.data.object.id }}"},
        trigger="webhook",
        before=[{
            "id": "failed_event",
            "type": "filter",
            "name": "Only Failed Payments",
            "parameters": {
                "conditions": [{
                    "id": "event_type",
                    "left": "{{ $json.type }}",
                    "operator": "is equal to",
                    "right": "payment_intent.payment_failed",
                    "combinator": "AND",
                }],
            },
        }],
        after=[
            {
                "id": "dunning",
                "type": "resend",
                "name": "Send Dunning Email",
                "parameters": {
                    "operation": "send_email",
                    "from": "{{ $env.BILLING_FROM_EMAIL }}",
                    "to": "{{ $node.action.json.receipt_email }}",
                    "subject": "Update your payment method",
                    "text": (
                        "We could not process your latest payment. "
                        "Please update your card to keep your workspace active."
                    ),
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify Billing Channel",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.BILLING_CHANNEL }}",
                    "text": "Dunning email sent for failed payment {{ $node.action.json.id }}.",
                },
            },
        ],
    ),
    _template(
        "NetSuite Month-End Close Snapshot",
        "Run a NetSuite SuiteQL snapshot for the current posting period, write it to the close workbook, and notify the finance team.",
        "finance", "netsuite", "query_suiteql",
        {
            "query": (
                "SELECT id, trandate, status, total FROM transaction "
                "WHERE postingperiod = '{{ $env.NETSUITE_PERIOD }}' ORDER BY trandate"
            ),
        },
        trigger="schedule",
        after=[
            {
                "id": "transaction_items",
                "type": "split",
                "name": "Split Transaction List",
                "parameters": {"field": "items"},
            },
            {
                "id": "sheet",
                "type": "google_sheets",
                "name": "Write Close Snapshot",
                "parameters": {
                    "operation": "append",
                    "spreadsheet_id": "{{ $env.FINANCE_SHEET_ID }}",
                    "range": "Month-End Close!A:D",
                    "values": [
                        "{{ $json.id }}", "{{ $json.trandate }}", "{{ $json.status }}", "{{ $json.total }}",
                    ],
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify Finance Close Channel",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.FINANCE_CHANNEL }}",
                    "text": "NetSuite month-end close snapshot has been written to the close workbook.",
                },
            },
        ],
    ),

    # --- DevOps and incident response --------------------------------------
    _template(
        "Sentry Regression Diagnosis to Jira",
        "Fetch the Sentry issue, use AI to diagnose the likely regression, and open a Jira bug with the diagnosis and first debugging steps attached.",
        "devops", "sentry", "get_issue",
        {"issue_id": "{{ $json.issue_id }}"},
        trigger="webhook",
        after=[
            {
                "id": "diagnosis",
                "type": "ai",
                "name": "Diagnose Regression",
                "parameters": {
                    "system_message": "You are an SRE. Identify the likely root cause, blast radius, and first debugging step.",
                    "prompt": "Diagnose this Sentry issue and propose a concrete fix.\n{{ JSON.stringify($node.action.json) }}",
                    "temperature": 0.2,
                },
            },
            {
                "id": "jira",
                "type": "jira",
                "name": "Open Regression Bug",
                "parameters": {
                    "operation": "create_issue",
                    "project_key": "{{ $env.JIRA_PROJECT_KEY }}",
                    "issue_type": "Bug",
                    "summary": "Regression: {{ $node.action.json.title }}",
                    "description": "{{ $json.response }}",
                },
            },
        ],
    ),
    _template(
        "PagerDuty Incident Postmortem Draft",
        "Fetch the PagerDuty incident, generate an AI postmortem draft, store it in Google Docs, and link it back to the incident channel.",
        "devops", "pagerduty", "get_incident",
        {"incident_id": "{{ $json.incident_id }}"},
        trigger="webhook",
        after=[
            {
                "id": "postmortem",
                "type": "ai",
                "name": "Draft Postmortem",
                "parameters": {
                    "system_message": "You are an incident commander. Write a blameless postmortem with timeline, impact, root cause, and follow-ups.",
                    "prompt": "Draft a postmortem from this PagerDuty incident.\n{{ JSON.stringify($node.action.json) }}",
                    "temperature": 0.3,
                },
            },
            {
                "id": "doc",
                "type": "google_docs",
                "name": "Create Postmortem Doc",
                "parameters": {
                    "operation": "create_document",
                    "title": "Postmortem draft — {{ $node.action.json.incident.title }}",
                },
            },
            {
                "id": "doc_body",
                "type": "google_docs",
                "name": "Fill Postmortem Draft",
                "parameters": {
                    "operation": "append_text",
                    "document_id": "{{ $node.doc.json.documentId }}",
                    "text": "{{ $node.postmortem.json.response }}",
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Share Draft in Incident Channel",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.INCIDENT_BRIDGE_CHANNEL }}",
                    "text": (
                        "Postmortem draft created for {{ $node.action.json.incident.title }}: "
                        "https://docs.google.com/document/d/{{ $node.doc.json.documentId }}/edit"
                    ),
                },
            },
        ],
    ),
    _template(
        "GitHub Release Blocker Digest",
        "List open GitHub issues, keep the ones labeled as release blockers, and post a grouped digest to the release channel.",
        "devops", "github", "list_issues",
        {
            "owner": "{{ $env.GITHUB_OWNER }}",
            "repo": "{{ $env.GITHUB_REPO }}",
            "state": "open",
            "per_page": 100,
        },
        trigger="schedule",
        after=[
            {
                "id": "issue_items",
                "type": "split",
                "name": "Split Issue List",
                "parameters": {"field": "issues"},
            },
            {
                "id": "blockers",
                "type": "filter",
                "name": "Keep Release Blockers",
                "parameters": {
                    "conditions": [{
                        "id": "label",
                        "left": "{{ $json.labels }}",
                        "operator": "contains",
                        "right": "release-blocker",
                        "combinator": "AND",
                    }],
                },
            },
            {
                "id": "bundle",
                "type": "aggregate",
                "name": "Bundle Blocker List",
                "parameters": {"field": "blockers"},
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Post Release Digest",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.RELEASE_CHANNEL }}",
                    "text": "Open release blockers:\n{{ JSON.stringify($json.blockers) }}",
                },
            },
        ],
    ),
    _template(
        "Jira P1 Escalation to On-Call",
        "Filter P1 Jira events, load the issue, page the on-call service owner through PagerDuty, and open an incident Slack thread.",
        "devops", "jira", "get_issue",
        {"issue_key": "{{ $json.issue_key }}"},
        trigger="webhook",
        before=[{
            "id": "p1_filter",
            "type": "filter",
            "name": "Only P1 Issues",
            "parameters": {
                "conditions": [{
                    "id": "priority",
                    "left": "{{ $json.priority }}",
                    "operator": "is equal to",
                    "right": "P1",
                    "combinator": "AND",
                }],
            },
        }],
        after=[
            {
                "id": "page_oncall",
                "type": "pagerduty",
                "name": "Page On-Call Engineer",
                "parameters": {
                    "operation": "create_incident",
                    "title": "P1 escalation: {{ $node.action.json.fields.summary }}",
                    "service_id": "{{ $env.PAGERDUTY_SERVICE_ID }}",
                    "urgency": "high",
                    "description": "{{ JSON.stringify($node.action.json.fields.description) }}",
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Open Incident Thread",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.INCIDENT_BRIDGE_CHANNEL }}",
                    "text": "P1 escalated to on-call: {{ $node.action.json.fields.summary }}",
                },
            },
        ],
    ),

    # --- Data hygiene and stewardship --------------------------------------
    _template(
        "Airtable Duplicate Contact Audit",
        "Scan Airtable contacts, group records that share an email, and post the duplicate groups to the data operations channel for merge review.",
        "data", "airtable", "list_records",
        {
            "base_id": "{{ $env.AIRTABLE_BASE_ID }}",
            "table_name": "Contacts",
            "page_size": 100,
        },
        trigger="schedule",
        after=[
            {
                "id": "contact_items",
                "type": "split",
                "name": "Split Contact Records",
                "parameters": {"field": "records"},
            },
            {
                "id": "dedupe",
                "type": "code",
                "name": "Group Duplicate Emails",
                "parameters": {
                    "language": "javascript",
                    "code": (
                        "const groups = {};\n"
                        "for (const item of $input.all()) {\n"
                        "  const record = item.json || {};\n"
                        "  const fields = record.fields || {};\n"
                        "  const rawEmail = fields.email || fields.Email || record.email || record.Email;\n"
                        "  const email = String(rawEmail || '').trim().toLowerCase();\n"
                        "  if (!email) continue;\n"
                        "  if (!groups[email]) groups[email] = [];\n"
                        "  groups[email].push(record.id);\n"
                        "}\n"
                        "return Object.entries(groups)\n"
                        "  .filter(([, ids]) => ids.length > 1)\n"
                        "  .map(([email, ids]) => ({ json: { email, record_ids: ids } }));"
                    ),
                },
            },
            {
                "id": "bundle",
                "type": "aggregate",
                "name": "Bundle Duplicate Groups",
                "parameters": {"field": "duplicates"},
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Post Duplicate Audit",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.DATA_OPERATIONS_CHANNEL }}",
                    "text": "Airtable duplicate contact audit:\n{{ JSON.stringify($json.duplicates) }}",
                },
            },
        ],
    ),
    _template(
        "Google Sheets CRM Hygiene Sweep",
        "Read the CRM sheet, flag rows missing an owner or company, append them to a data quality sheet, and alert the data operations channel. Expects name, email, owner, company, stage, and updated_at columns.",
        "data", "google_sheets", "read",
        {"spreadsheet_id": "{{ $env.CRM_SHEET_ID }}", "range": "CRM!A1:F"},
        trigger="schedule",
        after=[
            {
                "id": "map_rows",
                "type": "code",
                "name": "Map Header Row to Records",
                "parameters": {
                    "language": "javascript",
                    "code": (
                        "const first = $input.all()[0] || {};\n"
                        "const payload = first.json || {};\n"
                        "const rows = Array.isArray(payload.rows) ? payload.rows : [];\n"
                        "if (!rows.length) return [];\n"
                        "const headers = (rows[0] || []).map((value) => String(value || '').trim());\n"
                        "return rows.slice(1).map((row) => {\n"
                        "  const record = {};\n"
                        "  headers.forEach((header, index) => {\n"
                        "    if (header) record[header] = row[index];\n"
                        "  });\n"
                        "  return { json: record };\n"
                        "});"
                    ),
                },
            },
            {
                "id": "missing_fields",
                "type": "filter",
                "name": "Missing Owner or Company",
                "parameters": {
                    "conditions": [
                        {
                            "id": "owner",
                            "left": "{{ $json.owner }}",
                            "operator": "is empty",
                            "right": "",
                            "combinator": "AND",
                        },
                        {
                            "id": "company",
                            "left": "{{ $json.company }}",
                            "operator": "is empty",
                            "right": "",
                            "combinator": "OR",
                        },
                    ],
                },
            },
            {
                "id": "quality_sheet",
                "type": "google_sheets",
                "name": "Append Data Quality Rows",
                "parameters": {
                    "operation": "append",
                    "spreadsheet_id": "{{ $env.CRM_SHEET_ID }}",
                    "range": "Data Quality!A:F",
                    "values": [
                        "{{ $json.name }}", "{{ $json.email }}", "{{ $json.owner }}",
                        "{{ $json.company }}", "{{ $json.stage }}", "{{ $json.updated_at }}",
                    ],
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Alert Data Operations",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.DATA_OPERATIONS_CHANNEL }}",
                    "text": "CRM hygiene sweep flagged rows with a missing owner or company.",
                },
            },
        ],
    ),
    _template(
        "PostgreSQL Orphaned Record Audit",
        "Find orders whose customer record no longer exists, export the orphan list to a spreadsheet, and notify the data engineering team.",
        "data", "postgres", "query",
        {
            "sql": (
                "SELECT o.id, o.customer_id, o.created_at FROM orders o "
                "LEFT JOIN customers c ON c.id = o.customer_id "
                "WHERE c.id IS NULL LIMIT 500"
            ),
        },
        trigger="schedule",
        after=[
            {
                "id": "orphan_items",
                "type": "split",
                "name": "Split Orphan Rows",
                "parameters": {"field": "rows"},
            },
            {
                "id": "sheet",
                "type": "google_sheets",
                "name": "Export Orphan List",
                "parameters": {
                    "operation": "append",
                    "spreadsheet_id": "{{ $env.DATA_QUALITY_SHEET_ID }}",
                    "range": "Orphans!A:C",
                    "values": ["{{ $json.id }}", "{{ $json.customer_id }}", "{{ $json.created_at }}"],
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify Data Engineering",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.DATA_OPERATIONS_CHANNEL }}",
                    "text": "PostgreSQL orphaned order audit completed. Review the exported list.",
                },
            },
        ],
    ),
    _template(
        "HubSpot Contact Data Quality Queue",
        "List HubSpot contacts, flag records without a company, and create Airtable data quality tasks for the revenue operations team.",
        "data", "hubspot", "list",
        {"object_type": "contacts", "limit": 100},
        trigger="schedule",
        after=[
            {
                "id": "contact_items",
                "type": "split",
                "name": "Split Contact Records",
                "parameters": {"field": "records"},
            },
            {
                "id": "missing_company",
                "type": "filter",
                "name": "Missing Company Property",
                "parameters": {
                    "conditions": [{
                        "id": "company",
                        "left": "{{ $json.properties.company }}",
                        "operator": "is empty",
                        "right": "",
                        "combinator": "AND",
                    }],
                },
            },
            {
                "id": "queue",
                "type": "airtable",
                "name": "Create Data Quality Task",
                "parameters": {
                    "operation": "create_record",
                    "base_id": "{{ $env.AIRTABLE_BASE_ID }}",
                    "table_name": "Data Quality Queue",
                    "fields": {
                        "Email": "{{ $json.properties.email }}",
                        "Issue": "Missing company",
                        "Owner": "{{ $json.properties.hubspot_owner_id }}",
                    },
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify Revenue Operations",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.DATA_OPERATIONS_CHANNEL }}",
                    "text": "HubSpot contacts missing a company were added to the data quality queue.",
                },
            },
        ],
    ),

    # --- Commerce and order operations -------------------------------------
    _template(
        "Shopify High-Value Order Review",
        "Hold high-value Shopify orders for a human approval step before fulfillment and notify the operations channel when review is needed.",
        "commerce", "shopify", "get_order",
        {"order_id": "{{ $json.id }}"},
        trigger="webhook",
        before=[{
            "id": "value_filter",
            "type": "filter",
            "name": "High-Value Orders Only",
            "parameters": {
                "conditions": [{
                    "id": "total",
                    "left": "{{ $json.total_price }}",
                    "operator": "is greater than",
                    "right": 1000,
                    "combinator": "AND",
                }],
                "convertTypes": True,
            },
        }],
        after=[
            {
                "id": "approval",
                "type": "human_approval",
                "name": "Approve High-Value Fulfillment",
                "parameters": {
                    "message": (
                        "Order {{ $node.action.json.name }} totals {{ $node.action.json.total_price }}. "
                        "Review the order before fulfillment."
                    ),
                    "timeout_hours": 24,
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify Fulfillment Team",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.FULFILLMENT_CHANNEL }}",
                    "text": "High-value order {{ $node.action.json.name }} is awaiting fulfillment review.",
                },
            },
        ],
    ),
    _template(
        "Shopify Fulfillment Backlog Digest",
        "List open Shopify orders, keep the unfulfilled ones, and post a bundled backlog digest to the fulfillment channel each morning.",
        "commerce", "shopify", "list_orders",
        {"limit": 100, "order_status": "open"},
        trigger="schedule",
        after=[
            {
                "id": "order_items",
                "type": "split",
                "name": "Split Open Orders",
                "parameters": {"field": "orders"},
            },
            {
                "id": "unfulfilled",
                "type": "filter",
                "name": "Unfulfilled Orders",
                "parameters": {
                    "conditions": [{
                        "id": "fulfillment",
                        "left": "{{ $json.fulfillment_status }}",
                        "operator": "is not equal to",
                        "right": "fulfilled",
                        "combinator": "AND",
                    }],
                },
            },
            {
                "id": "bundle",
                "type": "aggregate",
                "name": "Bundle Open Orders",
                "parameters": {"field": "orders"},
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Post Backlog Digest",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.FULFILLMENT_CHANNEL }}",
                    "text": "Open Shopify orders needing fulfillment:\n{{ JSON.stringify($json.orders) }}",
                },
            },
        ],
    ),
    _template(
        "Stripe Refund Request Verification",
        "Verify a refund request against the original Stripe payment, issue the refund only for a succeeded payment, and email the customer.",
        "commerce", "stripe", "get_payment_intent",
        {"payment_intent_id": "{{ $json.payment_intent_id }}"},
        trigger="webhook",
        before=[{
            "id": "request_filter",
            "type": "filter",
            "name": "Only Refund Requests",
            "parameters": {
                "conditions": [{
                    "id": "request_type",
                    "left": "{{ $json.request_type }}",
                    "operator": "is equal to",
                    "right": "refund",
                    "combinator": "AND",
                }],
            },
        }],
        after=[
            {
                "id": "eligible",
                "type": "filter",
                "name": "Refundable Payment",
                "parameters": {
                    "conditions": [{
                        "id": "status",
                        "left": "{{ $json.status }}",
                        "operator": "is equal to",
                        "right": "succeeded",
                        "combinator": "AND",
                    }],
                },
            },
            {
                "id": "refund",
                "type": "stripe",
                "name": "Issue Stripe Refund",
                "parameters": {
                    "operation": "create_refund",
                    "payment_intent": "{{ $json.id }}",
                    "reason": "requested_by_customer",
                },
            },
            {
                "id": "email",
                "type": "gmail",
                "name": "Confirm Refund to Customer",
                "parameters": {
                    "operation": "send",
                    "to": "{{ $node.trigger.json.customer_email }}",
                    "subject": "Your refund has been issued",
                    "body_text": (
                        "A refund for payment {{ $node.action.json.id }} has been issued. "
                        "It may take 5-10 business days to appear on your statement."
                    ),
                },
            },
        ],
    ),

    # --- People operations -------------------------------------------------
    _template(
        "Workday New Hire Onboarding Packet",
        "Load the Workday worker record, create a Google Docs onboarding packet, email the new hire, and announce the start in the people channel.",
        "people", "workday", "get_worker",
        {"worker_id": "{{ $json.worker_id }}"},
        trigger="webhook",
        after=[
            {
                "id": "packet",
                "type": "google_docs",
                "name": "Create Onboarding Packet",
                "parameters": {
                    "operation": "create_document",
                    "title": "Onboarding packet — {{ $node.action.json.descriptor }}",
                },
            },
            {
                "id": "packet_body",
                "type": "google_docs",
                "name": "Fill Onboarding Checklist",
                "parameters": {
                    "operation": "append_text",
                    "document_id": "{{ $node.packet.json.documentId }}",
                    "text": (
                        "New hire: {{ $node.action.json.descriptor }}\n"
                        "Work email: {{ $node.trigger.json.work_email }}\n"
                        "Start date: {{ $node.trigger.json.start_date }}\n\n"
                        "Checklist:\n"
                        "- Confirm equipment and accounts\n"
                        "- Schedule manager 1:1 and team intro\n"
                        "- Review security and onboarding training"
                    ),
                },
            },
            {
                "id": "email",
                "type": "gmail",
                "name": "Email Onboarding Packet",
                "parameters": {
                    "operation": "send",
                    "to": "{{ $node.trigger.json.work_email }}",
                    "subject": "Welcome to the team",
                    "body_text": (
                        "Hi {{ $node.trigger.json.first_name }}, your onboarding packet is ready. "
                        "Document id: {{ $node.packet.json.documentId }}"
                    ),
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Announce New Hire",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.PEOPLE_CHANNEL }}",
                    "text": (
                        "Onboarding packet created for {{ $node.trigger.json.first_name }} "
                        "{{ $node.trigger.json.last_name }}."
                    ),
                },
            },
        ],
    ),
    _template(
        "Workday Requisition Approval Routing",
        "Create a Workday requisition, pause for hiring manager approval, and notify the recruiting channel when the request has been routed.",
        "people", "workday", "create_requisition",
        {
            "data": {
                "jobRequisitionId": "{{ $json.requisition_id }}",
                "openings": "{{ $json.openings }}",
                "hiringManager": "{{ $json.hiring_manager }}",
            },
        },
        trigger="webhook",
        after=[
            {
                "id": "approval",
                "type": "human_approval",
                "name": "Approve New Requisition",
                "parameters": {
                    "message": (
                        "Requisition {{ $node.action.json.jobRequisitionId }} needs hiring manager approval."
                    ),
                    "timeout_hours": 48,
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify Recruiting Channel",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.RECRUITING_CHANNEL }}",
                    "text": (
                        "Requisition {{ $node.action.json.jobRequisitionId }} is pending approval."
                    ),
                },
            },
        ],
    ),
    _template(
        "Interview Panel Scheduling Handoff",
        "Book the interview on the recruiting calendar, confirm the time with the candidate, and alert the panel in Slack.",
        "people", "google_calendar", "create_event",
        {
            "event": {
                "summary": "Interview — {{ $json.candidate_name }}",
                "description": "Panel interview for {{ $json.role }}",
                "start": {"dateTime": "{{ $json.start_time }}"},
                "end": {"dateTime": "{{ $json.end_time }}"},
            },
        },
        trigger="webhook",
        after=[
            {
                "id": "email",
                "type": "gmail",
                "name": "Confirm Interview with Candidate",
                "parameters": {
                    "operation": "send",
                    "to": "{{ $node.trigger.json.candidate_email }}",
                    "subject": "Interview confirmed",
                    "body_text": (
                        "Your interview is booked for {{ $node.trigger.json.start_time }}. "
                        "We look forward to speaking with you."
                    ),
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Alert Interview Panel",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.RECRUITING_CHANNEL }}",
                    "text": (
                        "Interview scheduled for {{ $node.trigger.json.candidate_name }} — "
                        "check the recruiting calendar."
                    ),
                },
            },
        ],
    ),
    _template(
        "DocuSign Offer Letter Completion Sync",
        "Check recent DocuSign envelopes, keep the completed offer letters, sync them to the HR tracker, and notify people operations.",
        "people", "docusign", "list_envelopes",
        {"from_date": "{{ $env.DOCUSIGN_SINCE }}", "count": 50},
        trigger="schedule",
        after=[
            {
                "id": "envelope_items",
                "type": "split",
                "name": "Split Envelope List",
                "parameters": {"field": "envelopes"},
            },
            {
                "id": "completed",
                "type": "filter",
                "name": "Completed Offer Letters",
                "parameters": {
                    "conditions": [{
                        "id": "status",
                        "left": "{{ $json.status }}",
                        "operator": "is equal to",
                        "right": "completed",
                        "combinator": "AND",
                    }],
                },
            },
            {
                "id": "sheet",
                "type": "google_sheets",
                "name": "Sync HR Tracker",
                "parameters": {
                    "operation": "append",
                    "spreadsheet_id": "{{ $env.HR_SHEET_ID }}",
                    "range": "Offers!A:D",
                    "values": [
                        "{{ $json.envelopeId }}", "{{ $json.status }}",
                        "{{ $json.completedDateTime }}", "{{ $json.emailSubject }}",
                    ],
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Notify People Operations",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.PEOPLE_CHANNEL }}",
                    "text": "Completed DocuSign offer letters were synced to the HR tracker.",
                },
            },
        ],
    ),

    # --- AI-assisted knowledge workflows -----------------------------------
    _template(
        "Slack Thread to Notion Runbook Capture",
        "Turn a Slack incident thread into an AI-drafted runbook page in Notion, ready for the team to review and publish.",
        "knowledge", "slack_api", "get_channel_history",
        {"channel": "{{ $json.channel_id }}", "limit": 100},
        trigger="webhook",
        after=[
            {
                "id": "runbook",
                "type": "ai",
                "name": "Draft Runbook from Thread",
                "parameters": {
                    "system_message": "You are a staff engineer. Extract symptoms, diagnosis, steps taken, and prevention ideas.",
                    "prompt": "Turn this Slack thread into a concise runbook.\n{{ JSON.stringify($json) }}",
                    "temperature": 0.2,
                },
            },
            {
                "id": "page",
                "type": "notion",
                "name": "Create Notion Runbook Page",
                "parameters": {
                    "operation": "create_page",
                    "database_id": "{{ $env.NOTION_RUNBOOK_DATABASE_ID }}",
                    "properties": {
                        "Name": {
                            "title": [{
                                "text": {
                                    "content": "Runbook draft: {{ $node.trigger.json.channel_name }}",
                                },
                            }],
                        },
                        "Notes": {
                            "rich_text": [{
                                "text": {"content": "{{ $json.response }}"},
                            }],
                        },
                    },
                },
            },
        ],
    ),
    _template(
        "Notion Support Macro Gap Finder",
        "Review the Notion support macro library with AI, identify missing or overlapping macros, and post the gaps to the support operations channel.",
        "knowledge", "notion", "query_database",
        {"database_id": "{{ $env.NOTION_MACRO_DATABASE_ID }}", "page_size": 100},
        trigger="schedule",
        after=[
            {
                "id": "gap_review",
                "type": "ai",
                "name": "Find Macro Gaps",
                "parameters": {
                    "system_message": "You are a support knowledge manager. Identify missing macros, overlap, and stale content.",
                    "prompt": "Review this support macro library and list the highest-value gaps.\n{{ JSON.stringify($json) }}",
                    "temperature": 0.2,
                },
            },
            {
                "id": "notify",
                "type": "slack_api",
                "name": "Post Macro Gap Review",
                "parameters": {
                    "operation": "send_message",
                    "channel": "{{ $env.SUPPORT_OPERATIONS_CHANNEL }}",
                    "text": "Support macro gaps identified:\n{{ $json.response }}",
                },
            },
        ],
    ),
]

CONNECTOR_TEMPLATES.extend(CURATED_BUSINESS_TEMPLATES)


# Schema-derived starter templates cover the long tail of native operations.
# They are generated by scripts/generate_template_catalog.py and never claim
# to be curated workflows: descriptions and environment placeholders make the
# setup work explicit.
from app.templates.generated import GENERATED_TEMPLATES  # noqa: E402

CONNECTOR_TEMPLATES.extend(GENERATED_TEMPLATES)
