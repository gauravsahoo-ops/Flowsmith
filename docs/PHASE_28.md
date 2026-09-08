# Phase 18 — Complete End-to-End Testing

> **Milestone:** the full user journey — login → create workflow → add
> Salesforce nodes → configure credentials → set operation params →
> save → run → worker executes against a real HTTP Salesforce endpoint →
> execution history + trace shown in the UI — is now covered by Playwright
> against a **local Salesforce REST emulator** on `127.0.0.1:8181`.
> **Status:** done — full backend suite 521 passed, vitest 24 passed,
> 6/6 e2e passed (3 new Salesforce scenarios), pyright clean.
> **Scope:** frontend e2e infra only; no unrelated Salesforce changes.

## 1. What already existed (not duplicated)

- Playwright setup (`frontend/playwright.config.ts`) with backend +
  stub webServers, existing e2e specs (save-reload, happy-path, delete
  workflow) — all still passing.
- Backend SSRF protection (`SafeHTTPClient`, spec 37.28) — blocks
  loopback/private hosts and non-80/443 ports for ALL connector traffic,
  including the Salesforce provider.
- The Salesforce connector/provider, IF-condition node, execution engine,
  trace API, and history UI — all unit-tested and passing.

## 2. The e2e gap and the plan

The happy-path e2e only exercised the `http_request` node against the
local stub — **no connector that uses `SafeHTTPClient` could be e2e-tested**
because the stub runs on `127.0.0.1:8181` and SSRF policy blocks it.
The Salesforce connector is the richest integration (token flow, SOQL,
CRUD), so the phase made it end-to-end testable:

1. **Dev/e2e SSRF escape hatch** — env-gated, OFF by default.
2. **Stub rewritten** as a faithful Salesforce REST emulator.
3. **Playwright backend started** with the escape-hatch env vars.
4. **Three Salesforce e2e scenarios** (A/B/C) with UI-driven setup.

## 3. SSRF escape hatch (backend, `app/security/safe_http_client.py`)

- `SAFE_HTTP_ALLOWED_HOSTS` / `SAFE_HTTP_ALLOWED_PORTS` — read ONCE when
  the default singleton is first created.
- **Exact-match** host allowlist checked **before** the blocklist; env
  ports are **union-ed** with the strict defaults `{80, 443}` (they never
  replace protection). Invalid env entries are ignored.
- Applies **only** to the `get_safe_http_client()` singleton — explicit
  `SafeHTTPClient(...)` instances are never affected.
- Documented as a dev/e2e facility that must not be set in production
  (and the Playwright backend is the only consumer).
- Tests: `tests/test_safe_http_client_hardening.py` (+4: exact
  host/port bypass, env off by default, env applied when set, env
  reaches the stub) — 15 passed with the existing SSRF suites.

## 4. Salesforce stub emulator (`frontend/tests/e2e/stub-server.mjs`)

Replaced the one-shot stub with a small in-memory Salesforce org:

- `POST /services/oauth2/token` → `access_token` + `instance_url`
  pointing back at `http://127.0.0.1:8181` (so the provider's real
  instance-URL resolution is exercised).
- `GET /services/data/{v}/query?q=SOQL` — parses
  `SELECT … FROM <Obj> [WHERE field = 'value'] [LIMIT n]` against the
  in-memory record store.
- `GET/POST/PATCH/DELETE /services/data/{v}/sobjects/{obj}[/{id}]` —
  create ids are 15-char alphanumeric (Salesforce-style), 404 body is
  the real `[{errorCode: 'NOT_FOUND', message, …}]` shape, PATCH merges
  fields.
- Seeded Lead `00Q000000000001` (Email `ada.e2e@example.com`,
  Company `Original Co`, Name `Ada Lovelace`) — makes the Search→Update
  scenario deterministic and re-runnable.
- `/health` + legacy `/get` kept for the happy-path spec.

## 5. Playwright wiring (`frontend/playwright.config.ts`)

- Backend webServer now starts with
  `SAFE_HTTP_ALLOWED_HOSTS=127.0.0.1`, `SAFE_HTTP_ALLOWED_PORTS=8181`
  and `reuseExistingServer: false` (a stale backend without the env
  would fail the Salesforce runs with confusing SSRF errors).
- Stub keeps `reuseExistingServer: true` but the stale-process trap
  (port 8181 held by an old stub) is a known startup symptom.

## 6. E2E scenarios (`frontend/tests/e2e/salesforce-e2e.spec.ts`)

All three register a user, create the credential through the
**credentials UI panel**, and build the workflow through the **store
(`window.__wfStore`)**, saving and running through the **real UI**.

- **A. Salesforce Search** — search `Lead` by `Email = ada.e2e@example.com`;
  asserts the run succeeds, the history row + inspector show the result,
  the trace reports `found: true`, and the stub really was queried
  (record values verified against `GET …/Lead/00Q000000000001`).
- **B. Search → IF (true) → Update** — the IF condition
  `$json.found equals true` routes to the **true** handle; update sets
  `Company = 'E2E Updated Co'` via `{{ $json.record.Id }}`; asserts the
  update step succeeded and the stub record really changed.
- **C. Search → IF (false) → Create** — searches a per-run unique email,
  condition `$json.found equals true` evaluates **false**, the **false**
  handle routes to create; asserts the new record id (15 chars) and the
  stub really holds the created Lead.

### Bugs the spec surfaced and how they were fixed (all in the spec)

- **Credential labels**: the UI shows pydantic auto-titles from
  `SalesforceCredential` — "Instance Url" (not "Instance/Login URL").
- **Stale zustand snapshot**: `getState()` before a mutation is stale —
  always re-fetch after `addNode`/`updateNode`.
- **Wrong node id after `addNode`**: with two `salesforce` nodes, "first
  node of type" returned the search node for the update/create wiring —
  creating a REAL cycle (`if_condition_1 ↔ salesforce_1`) that the
  backend correctly rejected with `Workflow contains a cycle`. The helper
  now returns the **last** node of the type (the just-added one).
- **Minimap swallows node clicks**: node selection (to open the config
  panel) is done by dispatching a synthetic `MouseEvent` click — the
  `CustomNode` onClick is the app's own selection path.
- **IF condition polarity**: wiring the create node to the `false`
  handle requires the condition `$json.found equals true` — with
  `equals false`, `found=false` matches and wrongly takes the true
  branch, so the create node never runs (3/4 success nodes).
- **`.run-status` strict-mode collision**: the inspector also renders
  `.run-status` once an execution is loaded — the assertion is scoped to
  `.topbar .run-status`.
- **Trace payload cap (spec 26)**: `_cap` bounds nested trace payloads
  at depth 4, so `record.*` values show as `"[truncated] (str)"` — the
  record is verified against the stub instead of the trace.

## 7. Verification

- `npx playwright test` → **6 passed** (3 existing + A/B/C).
- `npx vitest run` → **24 passed**.
- Backend: `pytest tests/test_safe_http_client*.py` → **15 passed**;
  full `pytest -q` → **521 passed**.
- Pyright: clean on changed `app/` code (`safe_http_client.py`).

## 8. Notes for the future

- The escape hatch is intentionally environment-specific; production
  deployments must never set `SAFE_HTTP_ALLOWED_HOSTS`/`_PORTS`.
- If the Salesforce e2e suite flakes with SSRF errors, check that no
  stale backend/stub is squatting on ports 8000/8181.
