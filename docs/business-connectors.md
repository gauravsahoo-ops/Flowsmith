# Phase 11 — Business Connectors

> **Status:** implemented on the Connector SDK; **not provider-validated**.
> Every connector is covered by seam-level tests (scripted SafeHTTPClient /
> fake engines / fakeredis), but none has been exercised against a real
> production tenant of the provider. Before relying on one, run its suite
> AND a manual live check with real credentials.

## What shipped

The 19 priority connectors from the Phase 11 spec. Four pre-existed
(HTTP, Gmail, Google Sheets, HubSpot); this phase adds the other 15.

| # | Connector | node type | Auth | Operations | Pagination | Notes |
|---|-----------|-----------|------|------------|------------|-------|
| 1 | HTTP *(existing)* | `http` | api key/basic | query/get/create/… | — | legacy generic ops |
| 2 | PostgreSQL | `postgres` | DSN credential (encrypted) | query, execute, insert_rows, list_tables | LIMIT cap (1000) | SQLAlchemy Core, off-loop thread; scheme allowlist |
| 3 | MySQL | `mysql` | DSN credential | same as postgres | same | pymysql driver |
| 4 | Gmail *(existing)* | `gmail` | OAuth (Connect Gmail) | send | — | |
| 5 | Google Sheets *(existing)* | `google_sheets` | OAuth (Connect Sheets) | read/append/update | — | |
| 6 | Google Drive | `google_drive` | OAuth (**Connect Google Drive**, new) | list_files, upload_file, get_file | nextPageToken loop (max_pages) | multipart upload (text/base64) |
| 7 | Slack | `slack_api`¹ | bot token (xoxb…) | send_message, list_channels | cursor (max_pages) | legacy webhook-only `slack` node untouched |
| 8 | Microsoft Teams | `msteams` | client-credentials app (`microsoft_graph`) | send_message, list_teams, list_channels | — | token cached per credential blob |
| 9 | GitHub | `github` | PAT / fine-grained token | get_repo, create_issue, add_comment, list_issues | page/per_page loop | X-RateLimit budget → retryable RATE_LIMITED |
| 10 | Microsoft Outlook | `outlook` | client-credentials app (`microsoft_graph`, shared w/ Teams) | send, list_messages | $top window | |
| 11 | HubSpot *(existing)* | `hubspot` | OAuth / private token | search/get/create/update | — | |
| 12 | Notion | `notion` | integration token | query_database, create_page, update_page | start_cursor loop | Notion-Version header |
| 13 | Jira | `jira` | basic auth (email + API token) | search (JQL), create_issue, update_issue, add_comment | startAt loop | https-only site pinning; ADF descriptions |
| 14 | Discord | `discord` | bot token *or* per-call webhook URL | send_message, send_webhook | — | Bot auth scheme; 2000-char cap enforced locally |
| 15 | Stripe | `stripe` | secret key (Bearer) | create/get/list customers, create_payment_intent | starting_after loop | **execution-scoped Idempotency-Key on writes** |
| 16 | MongoDB | `mongodb` | URI credential (encrypted) | find, insert_one, update_one, delete_one | skip/limit | pymongo optional dep; ObjectId → str sanitisation |
| 17 | Redis | `redis` | URI credential, falls back to REDIS_URL | get, set, delete, incr, publish | — | redis-py asyncio |
| 18 | Airtable | `airtable` | personal access token | list/get/create/update records | offset cursor loop | base/table id validation |
| 19 | Shopify | `shopify` | Admin API token + myshopify.com domain | get/list/create product, get_order | Link-header page_info loop | leaky-bucket 429 + Retry-After honored |

¹ The legacy `slack` **node class** owns that node type (engine prefers node
classes), so the connector registers as `slack_api`.

## Cross-cutting behaviour

- **Auth**: all secrets live in encrypted credentials (`app.credentials.registry`);
  server-side app credentials (Google OAuth, never per-user secrets) stay in env.
  New credential types: `postgres, mysql, google_drive, microsoft_graph,
  slack, github, notion, jira, discord, stripe, mongodb, redis, airtable, shopify`.
- **Errors**: typed only — `make_connector_error(ConnectorErrorCode.*, …)`.
  Taxonomy: 401→AUTH_FAILED, 403→FORBIDDEN, 404→NOT_FOUND, 429→RATE_LIMITED
  (retryable), 5xx/network/timeouts→UNAVAILABLE/TIMEOUT (retryable), everything
  else BAD_REQUEST (non-retryable).
- **Rate limits**: 429s are retryable and carry the provider's `Retry-After`
  (Slack, Stripe, Shopify, Airtable, Notion, Discord); GitHub's header-based
  budget exhaustion (403 + `X-RateLimit-Remaining: 0`) maps to RATE_LIMITED too.
- **Retries**: engine honours each operation's declared idempotency/retryability.
  Reads are retryable; side-effectful writes are `non_idempotent` — except
  Stripe writes, which are safe to retry because they carry an Idempotency-Key
  derived from `(execution_id, operation, payload)` — stable across engine
  retries of one logical write, different across executions.
- **Pagination caps**: every list operation takes `max_pages` so workflows can't
  loop forever against a chatty account.
- **Secret hygiene**: no credential value ever enters node params, traces,
  execution records or discovery payloads (asserted by tests).

## Frontend configuration

Nothing bespoke was needed beyond definitions — the SDK contract drives the UI:

- `GET /api/nodes` merges every connector's operations/input schemas into the
  catalog, so each new node type is draggable and configurable via JsonForm;
- `GET /api/credentials/types` renders credential forms from the validation
  schemas (secret fields masked);
- one new UI affordance: **Connect Google Drive** button (+ reconnect) in
  `CredentialsPanel.jsx`, wired to the new `google_drive` OAuth spec.

## Framework fixes made along the way

1. **Google OAuth scope bug (pre-existing):** `_google_authorize_url` hardcoded
   the Calendar spec's scopes, so Sheets/Gmail connects requested the wrong
   consent scope. Each Google provider now builds its authorize/token callables
   from a factory bound to its own `config_prefix`/scopes setting;
   `google_sheets_scopes` was missing from Settings entirely and is now defined.
   Duplicate `gmail_scopes` setting removed.
2. **`BaseProviderClient.authorized_request`** gained three optional params:
   `headers_extra` (Notion-Version etc.), `form_body` (Stripe form encoding),
   `auth_scheme` ("Bot" for Discord), plus an `on_response` hook that lets a
   provider inspect responses before generic >=400 handling (GitHub rate-limit
   headers). Static-token credentials (no refresh_token) no longer trigger a
   pointless 401 re-mint round-trip.

## Tests

Per-connector suites under `backend/tests/test_api/` (~90 cases) following the
established seams: scripted SafeHTTPClient (`_connector_fakes.py`), fake SQL
engines, fake MongoClient over the real pymongo/bson, fakeredis. Plus
`test_business_connectors_contract.py`: discovery completeness for all 19,
catalog/credential-type surfacing, definition↔connector dispatch parity,
idempotency vocabulary, secret-leak scan. Full stack (API→queue→worker→
engine→connector) proven for Postgres and Stripe.

## Provider validation status

**Not validated against live providers.** To validate a connector before
production use: create a sandbox/test tenant credential, run its test suite,
then execute one read op and one harmless write op through a scratch workflow
and confirm the provider's audit log shows exactly those calls.
