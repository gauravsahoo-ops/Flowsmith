# Built-in Workflow Templates

Flowsmith ships **330 built-in templates** in the public template gallery:
130 curated scenarios plus 200 schema-derived starter workflows covering the
long tail of native connector operations. Curated templates live in
[`backend/app/templates/library.py`](../backend/app/templates/library.py);
generated starters live in
[`backend/app/templates/generated.py`](../backend/app/templates/generated.py)
and are produced by `backend/scripts/generate_template_catalog.py`. The gallery
is seeded idempotently by `ensure_default_templates()` when opened.

Generated templates are explicitly marked as starters in their descriptions.
They derive required operation parameters from connector JSON schemas and use
`{{ $env.* }}` placeholders where an operator must supply a resource ID. They
are not presented as curated business recipes.

Admin-installed [connector packs](CONNECTOR_PACKS.md) can add additional public
templates. Those are pack-supplied and are not part of the 330 built-in count.

## Categories

The gallery covers:

- communication: Gmail, Slack, Outlook, Microsoft Teams, Discord, Twilio, WhatsApp
- CRM: HubSpot, Salesforce, Pipedrive, Zoho CRM, ActiveCampaign
- support: Zendesk, Freshdesk, Intercom, ServiceNow
- productivity: Notion, Asana, Trello, Monday, ClickUp, Google Docs,
  Google Calendar, Zoom, Calendly, Linear
- DevOps: Jira, GitHub, GitLab, Bitbucket, PagerDuty, Sentry
- data: Google Sheets, PostgreSQL, MySQL, BigQuery, Snowflake, Supabase, Typeform
- storage: Google Drive, Dropbox, Box, S3
- finance: Stripe, QuickBooks, Xero, DocuSign, NetSuite
- AI: OpenAI, Anthropic, Pinecone
- commerce/marketing: Shopify, Mailchimp, Brevo, Resend, SendGrid
- people/HR: Workday, Google Calendar, DocuSign

Each connector template uses a real registered native connector operation.
Generic templates use the built-in trigger, HTTP, AI, data-table, approval, and
set-data nodes.

## Validation

`backend/tests/test_template_catalog.py` checks:

- at least 330 unique templates exist;
- generated starters include every required operation parameter;
- every connector template references a registered connector node type and
  operation;
- every workflow graph has unique node IDs and valid connection endpoints;
- seeding is idempotent and produces the full gallery.

`backend/tests/test_api/test_templates.py` imports every default template into
a workflow, so broken template JSON fails CI.

## Seeding

The API seeds the gallery on first access. To seed explicitly:

```bash
python scripts/seed_templates.py
```

The script is idempotent and preserves use counts. Built-in template names are
reserved: they cannot be created, renamed, or deleted through the user template
API.
