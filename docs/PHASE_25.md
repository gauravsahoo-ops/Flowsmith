# Phase 25 — Retry and Idempotency for Salesforce Operations

> **Milestone:** every Salesforce operation now has a verified, documented
> retry/idempotency contract. Search/Get retry safely; Update/Delete retry
> and are idempotent by Salesforce semantics; Create is never blindly
> retried (duplicate risk). The engine's connector retry loop was
> hardened (node timeouts now retried, retry counts preserved in durable
> failure state), and the full behavior is locked down by engine-level
> and API-level tests.
> **Status:** done — 5 new tests (3 engine-level, 2 API-level) + definition
> contract tests extended; affected suites 140 passed, no regressions;
> Phase 15's error-handling suite (17 tests) stays green.

## 1. Retry model (engine, unchanged semantics)

- Settings: `retry_max_attempts` (default 1; max attempts = value + 1),
  `retry_backoff_seconds` (default 1.0), `timeout_seconds` (node-level).
- Exponential backoff: `backoff * 2^(k-1)` for retry k, capped at
  `MAX_RETRY_BACKOFF_S = 60s`.
- Only errors flagged `retryable` are retried: provider rate-limit
  (429), gateway/server errors (5xx), and **node timeouts** (this phase:
  a timeout on a connector call is now actually retried — previously the
  connector branch never retried `NodeTimeoutError` even though it is
  declared retryable).
- Retries emit `node.retry` events (`attempt`, `max_attempts`,
  `retry_after_s`, `error`); each attempt is capped by the node timeout.

## 2. Per-operation contract (Salesforce)

| Operation | Idempotent | Retryable (engine) | Rationale |
|---|---|---|---|
| `search` (SOQL) | Yes | Yes (429/5xx/timeout) | Read-only; safe to repeat |
| `get` | Yes | Yes | Read-only |
| `query` | Yes | Yes | Read-only |
| `update` (PATCH) | Yes | Yes | PATCH is a full overwrite; retry converges |
| `delete` | Yes | Yes | Deletes are idempotent (2nd call no-ops/404-safe) |
| `create` (POST) | **No** (`non_idempotent`) | **Never** | Blind retry would duplicate records; the connector forces every provider error to `retryable=False` |

Definition advertises this in metadata: `retryable` per operation and
`idempotency: "non_idempotent"` on create — a contract test
(`test_retryable_advertised_matches_runtime_semantics`) pins the
advertisement to the runtime behavior so the two can't drift.

## 3. Executor fixes

1. **Connector retry loop unifies retryable errors** — `ConnectorError`
   and `NodeTimeoutError` share one retry branch; an exhausted
   `NodeTimeoutError` keeps its `NODE_TIMEOUT` type (no masking).
2. **Retry counts survive failures** — connector-level retries were lost
   when a node finally failed (the failure note said "0 failed
   retries"); the error now carries `details: {"retries": N}` and the
   note counts them: *"Failed N attempt(s); M failed retries before this
   error."* Same for exhausted timeouts.
3. **Debug-only logging removed**; no redesign of the retry architecture.

## 4. Tests

- `backend/tests/test_salesforce_retry_idempotency.py` (engine-level):
  - search/get retried then succeed (trace note "succeeded after 1
    retries");
  - create: 429 and timeout are **not** retried, fails typed with
    `CONNECTOR_RATE_LIMITED` / `NODE_TIMEOUT` and 0 retry events;
  - update: backoff sequence `[0.03, 0.03]` with
    `MAX_RETRY_BACKOFF_S` patched to 0.03, budget exhaustion, and
    downstream node skip;
  - node timeout retried → success; exhausted → typed failure with
    retry count in the note.
- `backend/tests/test_api/test_salesforce_retry_history.py` (API-level,
  full stack): retried update leaves the trace note in execution
  history; a 429'd create records a typed `CONNECTOR_RATE_LIMITED`
  failure state (`retryable: false`) — and exactly one Salesforce call,
  proving no blind retry. (Split into two tests — the connector registry
  caches the OAuth token per instance, so a second run in the same test
  would skip the scripted token call.)
- `backend/tests/test_salesforce_definition.py` extended: retryable /
  idempotency contract tests.

## 5. Run

```powershell
cd backend
..\.venv\Scripts\python -m pytest tests/test_salesforce_retry_idempotency.py tests/test_api/test_salesforce_retry_history.py tests/test_salesforce_definition.py -q
```

Full regression: Salesforce connector/provider/definition/error-handling
suites + `test_executions.py` — **140 passed**. Pyright clean on the
changed `app/` files.