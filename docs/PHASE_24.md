# Phase 24 — Real Business Workflow: Salesforce Lead Sync

> **Milestone:** the primary Salesforce demonstration workflow — the
> classic "find-or-create / update-or-insert" business pattern, running
> through the production stack (API → job queue → worker → DAG engine →
> Salesforce connector → execution history), with both branches
> verified. The Salesforce HTTP layer is mocked for CI (deterministic,
> no org needed); real-org wiring is documented below.
> **Status:** done — 2 new full-stack tests green (both paths), full
> suite 460 passed (458 existing + 2 new); live-server seed verified
> (workflow listed in the UI API, run through the real worker).

## 1. The workflow

```text
Manual Trigger  (Run dialog: first/last name, email, company, phone)
      │
Set Data  "enrich"  (maps trigger input → FirstName/LastName/Email/
      │              Company/Phone/LeadSource="Web")
      ▼
Salesforce "sf_search"   operation=search, object=Lead,
      │                  search_field=Email
      ▼
IF "route"  (condition: $json.found equals true)
   /         \
 YES         NO
 │            │
 ▼            ▼
Salesforce   Salesforce
"sf_update"  "sf_create"
(update by    (create with the
record.Id)    full record)
```

- Node types: `manual_trigger`, `set_data`, `if_condition` (built-in
  engine), `salesforce` (connector framework, Phase 23).
- Data mapping via expressions:
  - `enrich` → `{{ $json.first_name }}` … (merge mode)
  - `sf_search.search_value` → `{{ $node.enrich.json.Email }}`
  - `sf_update.record_id` → `{{ $node.sf_search.json.record.Id }}`
  - `sf_update`/`sf_create.record` → `{{ $node.enrich.json.* }}`
- Branch wiring: `sourceHandle: "true"` → update, `"false"` → create;
  the skipped leg is recorded as `skipped`, never executed.
- The connector builds the real Salesforce calls: token
  (OAuth2 password grant) → `SELECT Id FROM Lead WHERE Email = '<v>' LIMIT 1`
  → `GET /sobjects/Lead/{Id}` (found) → `PATCH /sobjects/Lead/{Id}`
  (update) or `POST /sobjects/Lead` (create).

## 2. Verification (both paths, full stack)

`backend/tests/test_api/test_salesforce_lead_sync.py` drives the whole
production path exactly like a UI-created workflow: register → create
credential → `POST /api/workflows` → `POST /api/workflows/{id}/run`
(202 queued) → worker executes → poll detail. The Salesforce HTTP layer
is the only mock (SafeHTTPClient patch — same pattern as the existing
salesforce suites, and the only option: SafeHTTPClient's SSRF policy
blocks localhost/private hosts, so a fake org can't be reached by a
live server).

| Check | Existing lead → Update | Missing lead → Create |
|---|---|---|
| Execution status | `success` | `success` |
| Branch taken | `sf_update: success`, `sf_create: skipped` | `sf_create: success`, `sf_update: skipped` |
| `route` outputs | `true: [record]`, `false: []` | `true: []`, `false: [found:false]` |
| SOQL search value | `WHERE Email = 'jane@example.com'` | same |
| Salesforce call | `PATCH …/sobjects/Lead/00Qabc123` + resolved fields | `POST …/sobjects/Lead` + full record |
| Bearer / secrets | `Authorization: Bearer tok123`; no secrets leak into detail/items/trace/history | same |
| History | list/detail/items/trace re-fetchable | same |

Run:

```powershell
cd backend
..\.venv\Scripts\python -m pytest tests/test_api/test_salesforce_lead_sync.py -v
```

## 3. Frontend

The workflow lives in the running backend and appears on the React
canvas (sidebar → connectors → salesforce nodes; inspector shows each
node's parameters; Run dialog accepts the lead payload). Execution
results stream over the WebSocket and are inspectable per node.

Seed the live backend (creates demo user + credential + workflow):

```powershell
python scripts\seed_salesforce_lead_sync.py   # --base http://127.0.0.1:8000
```

Login on the frontend with the printed `demo.salesforce@example.com`
credentials to see **Salesforce Lead Sync** in the workflow list.

With the placeholder credential, running the workflow goes through the
whole live stack (202 → queue → worker → engine → connector) and the
Salesforce token call reaches `login.salesforce.com` for real — it
fails there with `CONNECTOR_AUTH_FAILED` until a real connected-app
credential replaces the placeholders (verified live:
`trigger/enrich success → sf_search error → route/sf_update/sf_create skipped`,
execution `failed` in history). The mocked CI tests cover the full
success paths deterministically.

## 4. Going live with a real org

1. In Salesforce: create a Connected App (Enable OAuth Settings,
   grant type *Username-Password Flow*), then add the security token
   to your password (`password+token`).
2. On the frontend **Credentials** page, edit the `SF Prod (demo)`
   credential and replace the placeholders:
   `instance_url` (login.salesforce.com, or test.salesforce.com for a
   sandbox), `client_id`, `client_secret`, `username`, `password`.
3. Run the workflow twice — once with an email that exists as a Lead
   (Update), once with a new email (Create) — and verify the created/
   updated records in Salesforce.
