# Phase 14 — First-class workflow testing

> **Milestone:** every workflow gets saved, repeatable tests. A test
> bundles **test data** (trigger items), **mock connector/HTTP
> responses**, **assertions** and an **expected-outputs regression
> snapshot**; running it executes the real engine with mocks enforced
> and produces a PASS / FAIL / DIFF report persisted on the execution.
> The one hard rule: **a test run can never mutate production data** —
> matched outbound calls are answered locally, and *unmatched* outbound
> calls are blocked outright.

## 1. What a WorkflowTest is

```text
WorkflowTest (saved per workflow)
├── test_data         trigger items fed to the run ([...] | {...} | null)
├── mocks             HTTP mock rules — url_pattern glob + method + status/body
├── assertions        per-run/per-node checks (see §3)
└── expected_outputs  node → outputs snapshot; drift renders as DIFF
```

Running a test (`POST .../tests/{id}/run`) enqueues an ordinary
execution with `trigger="test"` and a `_test_run` payload. The worker:

1. installs the mock rules for the whole execution,
2. runs the exact workflow snapshot through the standard engine,
3. evaluates the spec into `results["tests"]`:

```json
{
  "pass": true, "verdict": "PASS", "summary": "5/5 checks passed",
  "execution_status": "success",
  "checks": [{"name": "...", "target": "fetch", "type": "output_equals",
              "result": "PASS", "message": "...",
              "expected": "...", "actual": "...", "diff": null}]
}
```

The execution row keeps the WORKFLOW's own terminal status; only the
report carries the verdict — a red regression never masquerades as a
crashed execution and vice versa.

## 2. Mock mode = production safety

Two independent interception points cover every outbound path:

| Path | Mechanism |
| --- | --- |
| Connector/provider calls (`get_safe_http_client()` — Salesforce, HubSpot, Stripe, all Phase-11 connectors) | `SafeHTTPClient.request` consults a ContextVar of compiled rules before any network activity |
| Built-in nodes (`ctx.http_client` — http_request, graphql, slack/telegram nodes, ai tools) | test runs wrap the shared client in `MockedHttpClient`, which intercepts before delegating |

Semantics at both points: **match → local answer**, **miss while mocks
are active → typed block error** (`no mock matched … production systems
are never contacted during tests`). A test with zero mock rules blocks
everything. The ContextVar propagates into parallel branches.

Two latent bugs were caught by the new tests while building this:
the original glob→regex compiler prefixed *every* literal with `.`,
doubling the required input length so patterns could essentially never
match; and scheme-less patterns anchored to the URL tail without
tolerating query strings (`?page=2` broke matching).

## 3. Assertions (PASS / FAIL)

| type | fields | meaning |
| --- | --- | --- |
| `workflow_succeeded` / `workflow_failed` | – | run status check |
| `node_status` | `node_id`, `expected` | success / error / skipped; a node that never ran reports `not_run` and does NOT satisfy `skipped` |
| `output_equals` | `node_id`, `path?`, `expected` | dotted path into the main items (`0.body.name`); mismatch carries a structural diff |
| `output_contains` | `node_id`, `path?`, `value` | substring/deep containment |
| `output_matches` | `node_id`, `path?`, `pattern` | regex search |
| `output_length` | `node_id`, `expected` | item count |
| `error_code` | `node_id`, `code` | pins the typed error a failing node must produce |

Unknown assertion types are rejected at the API edge (422); anything
that slips through surfaces as FAIL in the report, never a crash.

## 4. Regression snapshots (DIFF)

`expected_outputs` compares actual vs expected per node with a bounded
structural diff (`change` / `missing` / `extra` / `length` / `type`,
max 40 entries). Mismatches report result **DIFF** — same failure
semantics as FAIL, but rendered as an explicit diff in the UI. The
TestsPanel's “Capture from last run” seeds the snapshot from the most
recent successful non-test execution.

## 5. Files

```text
backend/app/
├── testing/service.py          # evaluate_test(): assertions + DIFF engine (pure)
├── security/http_mocks.py      # rules, strict blocking, MockedHttpClient
├── api/workflow_tests.py       # CRUD + POST /{id}/run (trigger="test")
├── models/workflow_test.py     # workflow_tests table (+ alembic migration)
└── execution_runtime.py        # _test_run wiring, _finish_test_run stamping
frontend/src/
├── components/TestsPanel.jsx   # editor + runner + PASS/FAIL/DIFF report UI
├── utils/testReport.js(+test)  # badge/diff/summary helpers (vitest)
backend/tests/
├── test_testing/test_http_mocks.py   # 7 node-level mock contract tests
├── test_testing/test_service.py      # 23 evaluation tests (every assertion, DIFF…)
└── test_api/test_workflow_tests.py   # 8 full-stack tests (queue → worker → report)
```

## 6. API

```
GET    /api/workflows/{wid}/tests            list (view perm)
POST   /api/workflows/{wid}/tests            create (edit perm) → 201
GET    /api/workflows/{wid}/tests/{tid}      read
PATCH  /api/workflows/{wid}/tests/{tid}      update
DELETE /api/workflows/{wid}/tests/{tid}      delete
POST   /api/workflows/{wid}/tests/{tid}/run  → 202 {execution_id}
```

Test runs appear in history with `trigger="test"` so they can be told
apart from production executions; audit events `workflow_test.create`
and `workflow_test.run` are recorded.

## 7. Verification

- Node-level: 30 unit tests green (`tests/test_testing`).
- Full stack: 8 tests drive the real queue/worker loop — green-path
  PASS with mocks, blocked-call FAIL naming the guard, snapshot DIFF,
  mocked-500 surfaced through outputs, access control.
- pyright 0 on touched modules; schema parity 24 tables;
  vitest 157/157; oxlint clean; vite build clean.
