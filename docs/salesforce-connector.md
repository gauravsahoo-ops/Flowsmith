# Salesforce Connector

The first-party Salesforce integration: connect to a Salesforce org with
OAuth2 (or the legacy username-password grant), then use `salesforce`
nodes in workflows to search, query, create, update, delete and describe
records through the Salesforce REST API.

Live-tested end-to-end against a real Salesforce Developer Edition org
(OAuth connect, token refresh, search, create including duplicate-rule
alerts, update, get, delete). See [Testing](#testing) for exactly what
was verified where.

---

## Architecture

```
Workflow engine (executor)
  └─ node type "salesforce" → SalesforceConnector (op_execute)
        ├─ input validation + typed errors        app/connectors/salesforce_connector.py
        └─ SalesforceProviderClient               app/providers/salesforce.py
              ├─ auth: refresh-token / password grant, token cache
              ├─ SOQL escaping, pagination (≤ 10 pages)
              └─ error translation → ConnectorError
                    └─ SafeHTTPClient             app/security/safe_http_client.py
                          ├─ SSRF protection, redacted logging
                          └─ retry-once on decompression errors
                                └─ Salesforce REST API
```

Layering rules:

- The engine never talks to Salesforce directly. It routes `salesforce`
  node types to the connector and passes per-user credentials in
  `context["credentials"]["salesforce"]`.
- Credentials are decrypted from the store right before execution and
  are **never** echoed back or logged (see `docs/security.md`).
- The connector and provider are also usable standalone (unit-tested as
  such) — the connector is what the engine calls.

---

## Salesforce authentication

Two OAuth2 grants are supported.

### 1. OAuth2 authorization-code + PKCE ("Connect Salesforce")

The recommended flow, driven from the UI:

1. In the credential form click **Connect Salesforce**.
2. The backend builds the Salesforce authorize URL with a
   `code_challenge` (S256) and stores the matching `code_verifier`
   server-side (10-minute expiry).
3. You authorize in Salesforce; the browser is redirected to
   `http://localhost:8000/api/auth/salesforce/callback`.
4. The backend exchanges the code + verifier for an access token and a
   **refresh token**, which is stored Fernet-encrypted in the
   credential row.
5. At run time the provider refreshes the access token automatically
   (cached in-process with a 2-hour TTL and a single-flight lock).

The Connected App's client id/secret are **server configuration** — the
provider merges them in at call time; they are never stored in the
credential or sent to the frontend.

### 2. Username-password grant (legacy)

A manual credential with `client_id`, `client_secret`, `username` and
`password` (append the security token for non-Dev-Hub orgs). Still
supported, but OAuth is preferred because it never exposes the
password and supports revocation.

### Auth details worth knowing

- The org **instance URL** returned by the token endpoint wins over the
  credential's `login_url`/`instance_url`.
- OAuth token exchanges always send `Accept-Encoding: identity` — a
  single-use authorization code must never be retried, and some
  Salesforce/F5 edge servers serve a malformed gzip stream that broke
  retried exchanges.
- A cached access token is reused across nodes in the same process.

---

## Credential setup

Create a `salesforce` credential (Secrets → Add credential → Salesforce).

**Via OAuth (recommended):**

| Field | Value |
|---|---|
| Connected App callback URL | `http://localhost:8000/api/auth/salesforce/callback` |
| Connected App scopes | `refresh_token full` (refresh_token is required) |
| Connected App PKCE | required (S256, always sent by the connector) |
| Login URL | your org — e.g. `https://orgfarm-xxxx-dev-ed.develop.my.salesforce.com` for a Developer Edition with a custom domain; default is `https://login.salesforce.com` |
| API version | `v63.0` default, e.g. `v60.0` |

Click **Connect Salesforce** and authorize.

**Via manual grant:** fill `client_id`, `client_secret`, `username`,
`password` directly. All values are encrypted at rest.

---

## Connector setup

The connector is discovered via the connector registry
(`GET /api/connectors`) and its `salesforce` node type appears in the
canvas sidebar under **Connectors**.

Per node, the **credential must be selected in the node config** and the
workflow saved. A node whose `credentials` map is empty runs with no
credentials and fails with `CONNECTOR_NOT_CONFIGURED` — the node config
panel is the only place to attach the credential reference.

---

## Available operations

All operations take the `salesforce` node params below. Expressions
like `{{ $node.set_data_1.json.email }}` are resolved by the engine
before the node runs.

| Operation | Params | Output |
|---|---|---|
| `search` | `object_name`, `search_field`, `search_value` | `{ found, record, object_name, search_field }` — exact `=` match, first hit fetched in full |
| `query` | `soql` | `{ records, totalSize, done, nextRecordsUrl }` — follows `nextRecordsUrl` up to 10 pages |
| `get` | `object_name`, `record_id` | `{ record }` |
| `create` | `object_name`, `record` (field map) | `{ id, success, duplicate_alert?, matched_records? }` |
| `update` | `object_name`, `record_id`, `record` (fields to set) | `{ id, success }` |
| `delete` | `object_name`, `record_id` | `{ id, success }` |
| `describe` | `object_name` | `{ name, label, fields: [{name, label, type}] }` |
| `list` | — | `{ sobjects: [{name, label, createable}] }` |

Common params: `timeout_seconds` (default 30, 1–300). `record` values
must be scalar (string/number/bool). Field and object names must match
`[A-Za-z_][A-Za-z0-9_.]*`.

---

## Workflow configuration

A typical Salesforce workflow:

```
manual_trigger → set_data → salesforce (search) → if_condition
                                                      ├─ true  → salesforce (update)
                                                      └─ false → salesforce (create)
```

Configure each `salesforce` node: pick the credential, the operation
and its params. In the IF node, branch on `{{ $json.found }}`.

See `docs/FINAL_DEMO_SALESFORCE.md` for the full 12-step UI walkthrough
of this exact workflow, and `docs/PHASE_24.md` for the seeded Lead Sync
demo.

---

## Search/Get example

Find a Lead by Email and use the result downstream:

```
Node: salesforce (search)
  Credential:   Salesforce (my-org)
  Operation:    search
  Object name:  Lead
  Search field: Email
  Search value: {{ $node.set_data_1.json.email }}
```

Output (node `salesforce_1`):

```json
{
  "found": true,
  "record": {
    "Id": "00Q...",
    "Name": "Demo Candidate",
    "Email": "demo@example.com",
    "Company": "ACME",
    "...": "..."
  },
  "object_name": "Lead",
  "search_field": "Email"
}
```

Downstream you can reference `{{ $node.salesforce_1.json.record.Id }}`.
When nothing matches, `found` is `false` and `record` is `null`.

---

## Create example

```
Node: salesforce (create)
  Credential:   Salesforce (my-org)
  Operation:    create
  Object name:  Lead
  Record:
    FirstName:  Demo
    LastName:   Candidate
    Company:    ACME
    Email:      {{ $node.set_data_1.json.email }}
```

Output:

```json
{
  "id": "00Q...",
  "success": true
}
```

If the org's duplicate rule fires in **alert mode** the record is still
created; the output then carries `"duplicate_alert": true` and the
recovered record id (see [Error handling](#error-handling)). Create is
non-idempotent and is **never** auto-retried by the engine.

---

## Update example

```
Node: salesforce (update)
  Credential:   Salesforce (my-org)
  Operation:    update
  Object name:  Lead
  Record id:    {{ $node.salesforce_1.json.record.Id }}
  Record:
    Company:    ACME (demo)
```

Output:

```json
{
  "id": "00Q...",
  "success": true
}
```

The record id must be a valid 15- or 18-character Salesforce id. Update
is idempotent, so provider errors keep their retryable classification
and the engine may retry it.

---

## IF workflow example

Create-or-update a Lead depending on whether it exists:

```
manual_trigger
  → set_data            email = "demo@example.com"
  → salesforce_1        search Lead by Email = {{ $node.set_data_1.json.email }}
  → if_condition        condition: $json.found equals true
      ├─ true  → salesforce (update)  record_id = {{ $node.salesforce_1.json.record.Id }}, Company = "ACME (demo)"
      └─ false → salesforce (create)  Email = {{ $node.set_data_1.json.email }}, Company = "ACME"
```

Run 1 (new email): search returns `found: false` → create branch → a new
Lead appears in the org. Run 2 (same email): search returns `found:
true` → update branch → the same Lead's Company changes. Both branches
were verified end-to-end through the full worker stack
(`tests/test_api/test_salesforce_lead_sync.py`) and the live run.

---

## Error handling

Errors are typed `ConnectorError`s; the workflow run fails at the node
and (unless `continue_on_error` is set) stops downstream nodes:

| Error | Trigger | Retryable |
|---|---|---|
| `BAD_REQUEST` | invalid params, invalid SOQL/fields, Salesforce 400 | no |
| `AUTH_FAILED` | token grant rejected (401/400), bad Connected App config | no |
| `FORBIDDEN` | 403 (no object/field permission) | no |
| `NOT_FOUND` | 404 (missing record/object) | no |
| `RATE_LIMITED` | 429 API requests exceeded | yes |
| `UNAVAILABLE` | 5xx, network failure, malformed token response | yes |
| `TIMEOUT` | request or token timeout | yes |
| `NOT_CONFIGURED` | no credential attached to the node | no |

**Duplicate rules (observed live):** when an org's duplicate rule fires
in **alert mode**, Salesforce still creates the record. The connector
detects this and reports success instead of failing:

- HTTP 300 "Use one of these records?" → success with
  `duplicate_alert: true`, the recovered record id (re-queried by
  Email), and `matched_records` when the body carries them.
- HTTP 400 `DUPLICATES_DETECTED` → the connector re-queries the record
  by its `Email`; if it was created, success with `duplicate_alert:
  true` and the recovered id; if not (block mode), the normal
  `BAD_REQUEST` error is raised.

---

## Retry behavior

- **Reads** (`search`, `query`, `get`, `describe`, `list`) and
  **update/delete** are idempotent: retryable errors (429, 5xx,
  timeout, network) are auto-retried by the engine with exponential
  backoff (capped).
- **Create** is non-idempotent: retrying an ambiguous failure can
  silently duplicate the record, so every provider error is re-raised
  as **non-retryable** and the engine never auto-retries a create.
- **OAuth code exchange** is never retried (a code is single-use); the
  callback re-directs instead. Decompression failures
  (`DecodingError`) are retried once with `Accept-Encoding: identity`.

---

## Limitations

- `search` is an exact `=` match on one field (`SELECT Id ... WHERE
  field = 'value' LIMIT 1`). No fuzzy matching, SOSL, or multi-field
  search.
- Duplicate-alert recovery re-queries by `Email` only; it does not
  recover when the created record has no `Email` field (the record is
  then reported with `id: null`, still a success).
- `query` follows at most 10 pages of `nextRecordsUrl`; page size is
  tunable per call with `Sforce-Query-Options: batchSize=N` (a lower
  batch size forces multi-page results on small data).
- `describe` returns `name`/`label`/`type` per field, not the full
  Salesforce metadata payload.
- The connector health check is configuration-based, not a live org
  probe.
- A cached access token is process-local; a long-lived process holds
  the token until its 2-hour TTL expires.
- Not live-tested against a real org: the duplicate-alert `matched_records`
  extraction (unit-tested; body structure varies by org). Live-verified:
  OAuth connect + callback + PKCE, refresh-token auth, `search`
  (found/not-found), `create`, duplicate-alert recovery (id recovered on
  both 300 and 400 alerts), `update`, `get`, `delete`, `query` (single
  page and multi-page pagination via `Sforce-Query-Options: batchSize`),
  `describe`, `list`, and a full UI workflow run — see
  `scripts/live_salesforce_slice.py`.

---

## Testing

Backend (all green, 559 tests total):

- `tests/test_salesforce_provider.py` — token fetch, SOQL escaping,
  query pagination, record CRUD, error translation, duplicate-alert
  300/400 paths
- `tests/test_salesforce_connector.py` — operation validation, output
  normalization, update retry on 429 through the engine
- `tests/test_salesforce_retry_idempotency.py` — retry classification
  per operation, backoff caps, create-never-retried
- `tests/test_api/test_salesforce_lead_sync.py` — the full Lead Sync
  workflow on both branches
- `tests/test_api/test_salesforce_create.py` / `test_salesforce_update.py`
  — full-stack API runs, error typing, retry history
- `tests/test_api/test_oauth.py` — PKCE connect/callback flow
- `tests/test_safe_http_client.py` — decompression retry,
  SSRF protection

Frontend: Playwright e2e `tests/e2e/salesforce-e2e.spec.ts` (6/6
passing). Type checking: `pyright` clean.

Run: `cd backend; .\.venv\Scripts\python -m pytest`

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `redirect_uri_mismatch` on authorize | Callback URL not added to the Connected App; add `http://localhost:8000/api/auth/salesforce/callback` |
| `invalid_request: missing required code challenge` | Connected App enforces PKCE; the connector always sends S256 challenge — re-connect after the fix |
| `CONNECTOR_NOT_CONFIGURED` at run | Node's `credentials` map is empty; select the credential in the node config and **save** the workflow |
| `DecodingError: incorrect header check` on token exchange | F5/httpx gzip quirk; handled automatically (identity encoding + one retry). Re-connect if a pre-fix failure left a bad state |
| `AUTH_FAILED: invalid_grant` | Refresh token revoked (e.g. password reset); reconnect the credential |
| `AUTH_FAILED` right after connect | Wrong client id/secret or login URL (custom-domain orgs must use `https://<org>.develop.my.salesforce.com`) |
| `RATE_LIMITED` | Salesforce API limits; retryable — reads auto-retry, creates fail the run by design |
| 400 `DUPLICATES_DETECTED` (record not created) | Duplicate rule in **block** mode; change the rule to alert, or use non-duplicate data |
| `INVALID_FIELD` in `query` | The field/object is not accessible to the connected user or is a custom field name typo |
| Trace shows `[truncated]` dicts | Fixed in the executor (depth 7); record fields render fully in the execution trace |
| Node succeeds but no record appears | Duplicate alert created the record but the output id is `null` (300 path); check the org by the search value |