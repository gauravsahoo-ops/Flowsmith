# Phase 19 — Worker and Recovery Testing

> **Milestone:** the Salesforce workflow is verified under **asynchronous
> execution** — queue execution, stateless-worker recovery, API restart,
> retry, timeout, cancellation, duplicate-delivery dedup, execution
> persistence and history consistency — and the API is proven to never
> execute workflows synchronously (202 + async worker path only).
> **Status:** done — full backend suite **531 passed** (521 prior + 10
> new), pyright clean. One real defect found and fixed (history
> ordering ties); the queue/worker architecture was **preserved**.
> **Scope:** `backend/tests/test_queue/test_worker_recovery.py` (7
> tests, worker-level), `backend/tests/test_api/test_async_worker_recovery.py`
> (3 tests, API-level), one minimal fix in `app/api/executions.py`.

## 1. What already existed (not duplicated)

- Worker/queue machinery (Phase 15, specs 13/34/58): `DbJobQueue`
  (atomic claim, execution_id dedup, stale-heartbeat recovery),
  stateless `QueueWorker`, embedded consumer in the API process and
  `python -m app.queue.worker` for external workers.
- Engine-level retry/timeout/cancel tests, queue unit tests (FIFO,
  exclusive claim, stale recovery, dedup) and API-level 202 tests —
  all already passing (521 tests before this phase).

## 2. The phase's question

Phase 18 proved the Salesforce workflow end-to-end through the UI +
API + embedded consumer. Phase 19 verifies the **asynchronous
operational properties** of that same path — what happens when the
worker crashes, the API restarts, jobs are delivered twice, executions
time out or are cancelled — using the Salesforce connector as the
workload. The tests exercise the real `DbJobQueue` + `QueueWorker` +
embedded consumer; the Salesforce org is a scripted fake client
patched over `app.providers.salesforce.get_safe_http_client` (same
pattern as `test_salesforce_dag.py`).

## 3. New tests — worker level (`tests/test_queue/test_worker_recovery.py`)

- **Queue execution**: job goes `queued -> claimed -> done` with one
  claim (`attempts == 1`), execution `queued -> success`; the search
  really hit the org (token POST, SOQL query with the right `WHERE`,
  record fetch).
- **Worker execution + persistence**: results / node_statuses / trace
  stored; trace steps ordered; no credential secrets in any stored
  payload.
- **Worker restart (stale claim)**: first worker claims and "crashes";
  a fresh worker recovers the stale claim and runs the job from the
  payload snapshot — `attempts == 2`, exactly one execution row, no
  duplicates.
- **Worker restart mid-execution**: crash after the execution was
  marked `running`; the re-run overwrites with ONE consistent outcome
  (stateless re-execution of the snapshot).
- **Retry**: 429 → engine retry → success; trace notes "1 retries";
  engine-level retries don't touch the job's claim count.
- **Timeout**: `settings.timeout_seconds` fires against a hanging data
  call → execution `timeout`, job `done`, partial results persisted.
- **Cancellation**: a retryable 429 fails; during the backoff the
  durable cancel flag flips and the retry loop raises
  `NodeCancelledError` → execution `cancelled`, job `done`.
- **Duplicate job delivery**: the second enqueue of the same
  `execution_id` is rejected by the dedup guard; exactly one job, one
  execution, one claim, one run.

## 4. New tests — API level (`tests/test_api/test_async_worker_recovery.py`)

- **The API never runs workflows synchronously**: with a data call
  that takes 2.5 s, `POST /run` returns 202 in < 1.5 s, the execution
  is still `queued|running` at response time, and it completes
  asynchronously afterwards via the worker.
- **API restart**: the embedded consumer is stopped (API process
  "down"), a job queued before the restart stays untouched; a fresh
  consumer picks it up on restart and runs it to success — the
  persisted execution row and job row survive, exactly one of each.
- **History consistency across failure + retry**: failed run then
  `POST /retry` (new execution, `trigger="retry"`, same snapshot
  version); history lists both newest-first with correct statuses and
  `workflow_name`; job rows mirror the execution outcomes (`failed` /
  `done`).

## 5. Real defect found and fixed (minimal, in scope)

`GET /api/executions` ordered by `started_at DESC` only. `started_at`
came from `server_default=func.now()` → SQLite `CURRENT_TIMESTAMP` has
**second resolution**, so executions created within the same second
tied, and the listing order (and therefore pagination) was
non-deterministic. The history-consistency test surfaced it.

Fix in `app/api/executions.py`:
- `start_execution` now sets `started_at=datetime.now(UTC)` explicitly
  (microsecond precision — creation order is accurate).
- The list query ties break on `id DESC` — deterministic, stable
  ordering across pages and refreshes.

The queue and worker architecture were left untouched.

## 6. Verification

- `pytest tests/test_queue/test_worker_recovery.py` → 7 passed.
- `pytest tests/test_api/test_async_worker_recovery.py` → 3 passed.
- Full backend suite `pytest -q` → **531 passed** (two consecutive
  clean full runs after the fix).
- Pyright clean on the changed app file.

## 7. Notes for the future

- Worker restart tests use `recover_stale_once(0)` (instant staleness);
  the production recovery still relies on the heartbeat sweep — that
  behavior is unit-tested in `tests/test_queue/test_db_queue.py`.
- The embedded-consumer lifecycle (`stop`/`ensure`) is global process
  state; the API tests manage it explicitly for the restart scenario.
