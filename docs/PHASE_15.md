# Phase 15 — Job queue, durable events and stateless workers

> **Milestone (M7, spec 13/34/58):** executions no longer run inline in
> the API process. A run creates a row in a real job queue
> (**`jobs`** table by default, **Redis** optionally) and a **worker**
> — the embedded consumer in the API process by default, or any number
> of stateless external `python -m app.queue.worker` processes — claims
> it, executes it and persists the outcome. Claims are atomic and
> exclusive (a job runs exactly once even with many workers), crashed
> workers are detected via a stale heartbeat and their jobs re-queued,
> cancellation works durably across processes, and event streaming
> stays live in-process while durable `execution_events` rows back
> external workers and late-connecting streams.
> **Status:** done — 26 new tests (11 db queue, 9 redis queue, 6
> worker integration) green; full suite 273 passed (was 247).

## 1. What Phase 15 delivers

```text
POST /workflows/{id}/run   webhook   scheduler
        │ (execution row "queued" + job enqueued)
        ▼
   job queue (jobs table | redis)          queue.claim() is ONE atomic
        │  ◄── embedded consumer (API      UPDATE ... RETURNING id /
        │       process, dev default)          LMOVE — exclusive
        ▼  ◄── external workers: python -m app.queue.worker (N replicas)
app/execution_runtime.run_job(job, sink)   shared by every consumer
        │  status: queued → running → success|failed|cancelled|timeout
        ▼
 durably persisted: execution row + execution_events rows
 WS stream: in-process bus (embedded) or events table (external)
```

- **`app/queue/`** — `QueueBackend` ABC + register/factory (`get_queue()`,
  `Settings.queue_backend`). Two backends, identical contract:
  - **`db_queue.py` (default, zero infrastructure)** — rows in the
    `jobs` table. Claim = one atomic `UPDATE … WHERE id = (SELECT id …
    ORDER BY created_at) RETURNING id`, so two workers can never take
    the same job, and the successful claim reads back the exact row.
    `enqueue` is idempotent per `execution_id` (unique constraint —
    duplicate delivery is rejected, spec 25). Heartbeats refresh
    `heartbeat_at`; recovery re-queues claims whose heartbeat is stale
    or missing (crashed workers, spec 34.1).
  - **`redis_queue.py` (optional)** — LPUSH queue + LMOVE atomic claim
    + per-job hash metadata (attempts, heartbeat); same semantics,
    `QUEUE_BACKEND=redis` + `REDIS_URL`.
- **`app/queue/worker.py`** — one loop shared by all consumers:
  `claim → run_job → complete`, a heartbeat task while a job runs, and
  a stale-claim sweep when idle. Two modes:
  - **Embedded consumer** — started lazily on the background runner in
    the API process (dev default `queue_embedded_consumer=true`); events
    stream over the in-process bus so the WebSocket behaves exactly as
    before.
  - **External worker** — `python -m app.queue.worker`: fully
    stateless, durable events via `_event_sink_to_db`, SIGINT/SIGTERM
    graceful stop. Run as many replicas as you like.
- **`app/execution_runtime.py`** — the shared `run_job(job, event_sink)`:
  flips `queued → running`, executes the workflow snapshot with
  credential resolution (moved from the old executions module),
  persists outcome/result/trace/error, links webhook deliveries,
  updates metrics. An exception can never lose the execution record.
- **Durable cancellation (spec 36)** — still cooperative, now
  process-safe: `POST …/cancel` persists `cancelling`; a monitor task
  in `run_job` polls that flag every 250ms and flips the engine's
  cancel event. Works whether the execution runs in this process or on
  an external worker, and survives restarts (a `cancelling` execution
  claimed later is terminal-cancelled without running).
- **`execution_events` table (spec 37)** — external workers persist
  every event (seq per execution); the WebSocket drains both the bus
  and the table each tick (separate watermarks; only one source is
  ever active per execution), so live streams and late connections
  work in both modes. Terminal events now carry the final `status`
  (previously only the event name implied it).
- **Config** (`config.py`) — `queue_backend`, `queue_embedded_consumer`,
  `worker_poll_interval_s`, `worker_heartbeat_s`, `worker_stale_seconds`,
  `worker_stale_sweep_s`, `queue_claim_timeout_s`, `redis_url`.

## 2. Why it took the shape it did (bugs found on the way)

1. **The naive claim has a double-execution race.** Reading back "the
   latest row claimed by me" after the UPDATE can pick up a *different*
   worker's job when two consumers share a worker id (same host/pid).
   Fix: `UPDATE … RETURNING id` and fetch exactly that row — the
   claim is unambiguous for any number of consumers.
2. **The WS handler "picked a source once"** (`bus` if any event was
   buffered at connect time, else `db`) — with the queue, a stream
   could connect while the execution was still `queued`, pick `db`,
   and then never see the in-process bus events. Now it drains **both**
   sources every tick with independent watermarks (each execution uses
   exactly one source in practice, so no duplicates or reorder issues).
3. **Claim-timeout as a wall-clock watchdog kills long runs.** Wrapping
   `consume_once` in `wait_for(claim_timeout)` cancels a legitimate
   10-minute workflow after 60s. Job timeouts are the engine's job
   (per-node + `timeout_seconds`); the worker must never impose its
   own.
4. **Cancelled-while-queued runs published no event.** `run_job`'s
   early terminal path marked the record `cancelled` but nothing
   reached the event streams; slow runs ahead in the consumer queue
   made the WS fall back to a bare `execution.terminal`. The early
   path now sinks the `execution.cancelled` event too (durable rows +
   live stream stay consistent, spec 37).
5. **sqlite `RETURNING` and the deprecation sweep** — claim relies on
   `UPDATE … RETURNING id`, supported by the bundled SQLite
   (≥3.35) and PostgreSQL; both are covered by the FIFO/exclusivity
   tests.

## 3. Files

```text
backend/app/
├── queue/                     # NEW
│   ├── __init__.py            #   QueueBackend ABC, registry, get_queue()
│   ├── db_queue.py            #   default backend: jobs table
│   ├── redis_queue.py         #   optional backend: real Redis
│   └── worker.py              #   embedded consumer + external worker
├── execution_runtime.py       # NEW: shared run_job(job, sink) + cancel watch
├── models/job.py              # NEW: jobs table (execution_id unique)
├── models/execution_event.py  # NEW: durable event rows (spec 37)
├── api/executions.py          # start_execution → enqueue; cancel persists flag
├── api/ws.py                  # dual-source drain (bus + events table)
├── engine/executor.py         # terminal events carry status
└── main.py                    # embedded consumer starts at lifespan
backend/tests/
├── test_queue/                # NEW
│   ├── test_db_queue.py       #   11 tests: FIFO, exclusive claim, complete,
│   │                          #     duplicate guard, stale recovery
│   ├── test_redis_queue.py    #   9 tests vs fakeredis (same contract)
│   └── test_worker.py         #   6 integration tests: run→done, durable
│                              #     events, cancel (DB flag), crash recovery,
│                              #     failure marking, heartbeats
└── test_api/                  # expect `queued` in poll helpers (transient)
                               # test_webhook_trigger waits for running after 202
```

## 4. Verification

- `pytest tests/test_queue` — 26 passed.
- Full suite **273 passed** (was 247); pyright clean.
- Smoke test of the external-worker path: `python -m app.queue.worker`
  consumes the same `jobs` table the API enqueues into
  (`QUEUE_BACKEND=db`), persists `execution_events`, and the WS
  stream plays back from those rows.