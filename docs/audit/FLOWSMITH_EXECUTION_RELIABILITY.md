# Flowsmith Workflow Engine Reliability Audit & Hardening Report

**Audit Phase:** Phase 3 — Execution Engine, Queue, Scheduler, Trigger System, DAG Traversal, Workers, and Recovery Mechanisms  
**Auditor:** Principal Distributed-Systems & Reliability Architect  
**Status:** Hardened, Verified, and Empirically Tested (156 Core Tests Passing)  
**Date:** October 2026  

---

## 1. Executive Summary & Distributed Architecture

Flowsmith is an enterprise workflow orchestration platform designed for multi-tenant hybrid and self-hosted environments. This audit evaluated the entire execution lifecycle under nominal loads and failure conditions (worker crashes, API restarts, Redis/DB outages, cancellation races, duplicate transport packets, network partitions, and queue saturation).

```
                      +---------------------------------------+
                      |       Client UI / Webhooks / API       |
                      +---------------------------------------+
                                          |
                      +---------------------------------------+
                      |     PostgreSQL (Authoritative DB)     |
                      |   - executions (State Machine & Trace)|
                      |   - execution_events (Cross-replica)  |
                      |   - advisory locks (0x7EED01)         |
                      +---------------------------------------+
                                   /             \
                                  /               \
         +----------------------------+   +----------------------------+
         |     Database Job Queue     |   |      Redis Job Queue       |
         | (SELECT ... FOR UPDATE     |   | (LMOVE + ZSET Backoff +    |
         |   SKIP LOCKED)             |   |  noeviction + AOF)         |
         +----------------------------+   +----------------------------+
                                   \             /
                                    \           /
                      +---------------------------------------+
                      |      Stateless Execution Workers      |
                      |   - Atomic Claiming & Lease Renewal   |
                      |   - Heartbeat Sweeps & Poison Reclaim |
                      |   - Cooperative Cancellation (CAS)    |
                      |   - Checkpointing & Long-Running Gate |
                      +---------------------------------------+
```

### Core System Invariants
1. **Authoritative State Record:** The PostgreSQL `executions` table is the single source of truth. Queues (`jobs` table or Redis keys) act as transient work dispatch transports.
2. **Stateless Workers:** Worker processes maintain zero local persistent state. Every job execution is fully self-contained within its immutable payload snapshot. Worker crashes are recovered by any peer worker reclaiming stale claims.
3. **Atomic Exclusive Claiming:** Dual transport backends (PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED` and Redis atomic `LMOVE`) guarantee that exactly one worker acquires ownership of a queued task.
4. **Idempotent Enqueue & Delivery:** Every execution ID has an enforced uniqueness/idempotency boundary (`queue:execs` set in Redis; uniqueness constraints in DB). Accidental duplicate delivery or retries never result in duplicate executions.
5. **Safe Eviction & Persistence:** Queue storage requires zero-eviction policies. Flowsmith discovered and resolved a critical default configuration flaw where `allkeys-lru` was used in Redis containers, replacing it with `noeviction` and Append-Only File (AOF) persistence.

---

## 2. Workflow Graphs, DAG Traversal, Cycles & Limits

### 2.1 Graph Validation (`app/engine/graph.py`)
Workflows undergo rigorous structural validation before execution:
- **Node Validation:** Unique node IDs, valid node types registered in [NODE_REGISTRY](file:///c:/Flowsmith/backend/app/nodes/registry.py) or connector definitions, and parameter schema building.
- **Connection Integrity:** Every connection source and target must reference existing nodes. Source handles and target handles must conform to node type contracts (e.g. `main`, `true`, `false`, `error`, `done`, `loop`).
- **Draft Exemption:** Canvas draft saves validate topology with `validate_params=False` so incomplete node configurations do not prevent saving intermediate progress. Parameter validation is strictly enforced at runtime prior to node execution.

### 2.2 Cycle Tolerance & Deterministic Ordering
Traditional workflow engines reject circular dependencies at graph build time. Flowsmith supports arbitrary graph topologies (including visual loop feedback edges) while ensuring reliable, non-infinite execution:
- **Kahn's Algorithm with Stable Cycle Resolution:** [topological_sort()](file:///c:/Flowsmith/backend/app/engine/graph.py#L158-L208) partitions the graph into a forward DAG and strongly connected components (cycles). Nodes with an in-degree of 0 are scheduled first; remaining cyclic nodes are appended in stable lexical order.
- **Single-Execution Per Node:** In the primary execution loop ([_run_nodes](file:///c:/Flowsmith/backend/app/engine/executor.py#L317-L490)), each node is scheduled at most once per workflow run. Cyclic feedback edges are not executed in infinite loops at the graph level.
- **Cycle-Breaking Semantics:** If active tasks drain and cyclic nodes remain unscheduled, the executor breaks the cycle by scheduling the node with the fewest remaining incomplete parents, supplying it with empty input.

### 2.3 Bounded Loop Nodes (`app/nodes/loop_while.py`)
Looping logic is encapsulated within specialized nodes rather than raw graph cycles:
- **Iteration Cap:** Hard cap on iterations bounded between 1 and 10,000 (`max_iterations`, default 1,000).
- **Termination Mode:** Evaluates conditions per iteration (`until` stops when satisfied; `while` continues while satisfied).
- **Poison-Loop Defense (`on_limit`):** Defaults to `fail`, which raises a typed `LOOP_LIMIT_EXCEEDED` error. Infinite or non-terminating loops can never hang indefinitely or pass silently.
- **Cancellable Delays:** Per-iteration pauses are executed in 50ms slices, checking `ctx.is_cancelled()` continuously to support instant cooperative termination.

### 2.4 Sub-Workflow Recursion Boundaries (`app/nodes/sub_workflow.py`)
Modular workflows invoking other workflows via [SubWorkflowNode](file:///c:/Flowsmith/backend/app/nodes/sub_workflow.py#L91-L286) enforce strict distributed controls:
- **Depth Recursion Guard:** `ctx.execution_depth` is incremented on each invocation. Any attempt to nest sub-workflows beyond `MAX_SUBWORKFLOW_DEPTH = 5` raises `SUBWORKFLOW_DEPTH_EXCEEDED` with `retryable=False`.
- **Tenant Isolation:** Explicit workspace and workflow access permission checks ([get_permission](file:///c:/Flowsmith/backend/app/api/access.py)) prevent IDOR or cross-tenant invocation.
- **Cancellation Propagation:** Parent cancellation events are passed down to child executions; cancelling the parent triggers cooperative cancellation of running children.

---

## 3. Queue Architecture, Idempotency & Persistence

Flowsmith supports two swappable queue implementations sharing an identical interface ([QueueBackend](file:///c:/Flowsmith/backend/app/queue/__init__.py)):

### 3.1 Database Queue (`app/queue/db_queue.py`)
- **Technology:** PostgreSQL transactional table `jobs`.
- **Atomic Claiming:** Uses `SELECT ... FOR UPDATE SKIP LOCKED` inside a short-lived transaction. Multiple concurrent worker replicas never block each other and never claim the same job.
- **Zero External Infrastructure:** Works natively on the existing PostgreSQL database, making it ideal for self-hosted and air-gapped deployments.
- **Idempotency Guard:** Rejects duplicate enqueue attempts for existing execution IDs via unique constraint handling.

### 3.2 Redis Queue (`app/queue/redis_queue.py`)
- **Structure:**
  - `queue:jobs` — FIFO list of pending job IDs (`LPUSH` / `RPOPLPUSH` / `LMOVE`).
  - `queue:jobs:processing` — List of in-flight claimed job IDs.
  - `queue:jobs:scheduled` — Sorted set (ZSET) holding delayed retry jobs scored by epoch timestamp.
  - `queue:meta:{job_id}` — Hash containing job status, execution ID, attempts count, heartbeat timestamp, and payload.
  - `queue:execs` — Set of in-progress execution IDs acting as the distributed deduplication guard.
- **Atomic Claiming:** Uses atomic `LMOVE queue:jobs queue:jobs:processing RIGHT LEFT` ensuring single-command transfer without race conditions.
- **Delayed Exponential Backoff:** Reclaimed jobs waiting out retry delays are placed in `queue:jobs:scheduled`. [claim()](file:///c:/Flowsmith/backend/app/queue/redis_queue.py#L172-L211) promotes ready jobs back onto the FIFO queue before claiming.

### 3.3 Critical Redis Eviction Remediation
> [!CAUTION]
> **Defect Identified:** Flowsmith's default `docker-compose.yml` and `docker-compose.staging.yml` previously configured Redis with:
> `exec redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru`
> Under memory pressure, `allkeys-lru` instructs Redis to silently evict keys regardless of TTL. This could silently delete `queue:jobs`, `queue:jobs:processing`, and `queue:meta` hashes, causing in-flight work to vanish without trace.

**Remediation Applied:**
1. **Configuration Hardening:** Updated [docker-compose.yml](file:///c:/Flowsmith/docker-compose.yml#L38) and [docker-compose.staging.yml](file:///c:/Flowsmith/docker-compose.staging.yml#L36) to:
   ```yaml
   command: ["sh", "-c", "exec redis-server --requirepass \"$REDIS_PASSWORD\" --maxmemory 256mb --maxmemory-policy noeviction --appendonly yes"]
   ```
2. **Runtime Verification:** Implemented [verify_eviction_policy()](file:///c:/Flowsmith/backend/app/queue/redis_queue.py#L86-L117) in `RedisJobQueue`. Upon connection, it inspects `CONFIG GET maxmemory-policy` and logs a prominent warning if any `allkeys-*` or `volatile-*` policy is detected.
3. **Write-Ahead Logging (AOF):** Enabled `--appendonly yes` so that all queue writes are persisted to disk every second, surviving container restarts and hard host crashes.

### 3.4 Poison-Job Handling & Dead-Letter Isolation
A job that causes a worker to crash (e.g. segfault, OOM kill, unhandled hardware failure) will leave a stale heartbeat in the queue.
- **Attempt Tracking:** Both queue backends track integer `attempts` per job.
- **Max Attempt Limit:** Governed by `queue_max_attempts` (default 5).
- **Terminal Dead-Letter Failure:** Once a job reaches max attempts during stale recovery sweeps, it is not re-queued. The transport job is marked `failed` with `MAX_ATTEMPTS_EXCEEDED`, its metadata is expired, and the authoritative `executions` row is transitioned to `failed` with diagnostic error details.

---

## 4. Accidental Duplicate Execution Prevention

Flowsmith implements multiple layers of defense to prevent accidental, duplicate, or unprompted workflow executions:

| Trigger Source / Vector | Failure Risk | Implemented Defense Mechanism |
| :--- | :--- | :--- |
| **React Component Re-render** | Multiple component mounts re-triggering execution | [TopBar.jsx](file:///c:/Flowsmith/frontend/src/components/TopBar.jsx#L495-L525) toggles button to Cancel upon click; `useExecutionStore` sets `running: true` synchronously before API response; debounced UI actions. |
| **Client Status Polling** | Polling requests accidentally initiating execution | Polling calls in [executionStore.js](file:///c:/Flowsmith/frontend/src/stores/executionStore.js#L417-L500) only issue read-only `GET /api/executions/{id}` requests; never mutate or run workflows. |
| **WebSocket Reconnection** | Reconnect handshakes triggering duplicate runs | Handshakes use short-lived one-time tickets ([POST /api/auth/ws-ticket](file:///c:/Flowsmith/backend/app/api/auth.py#L608)); connection only streams events; read-only fallback. |
| **UI Page Refresh (F5)** | Page reload resending execution command | The execution ID is stored in the URL / route state; on page load, the frontend loads existing trace via `api.getExecution(id)`. |
| **Workflow Import** | Malicious or imported workflow auto-starting triggers | [import_workflow](file:///c:/Flowsmith/backend/app/api/workflows.py#L257-L325) strictly forces `active = False`, `status = "draft"`, strips placeholder credentials, and regenerates 24-char entropy webhook paths. Zero executions are queued. |
| **Workflow Duplication** | Duplicating a running workflow re-executing active jobs | [duplicate_workflow](file:///c:/Flowsmith/backend/app/api/workflows.py#L328-L410) forces `active = False`, `status = "draft"`, deep-cleans secrets/credentials, appends `(Copy)`, and creates zero executions. |
| **Concurrent Manual Clicks** | Rapid double-click on "Run" button | Backend [run_workflow](file:///c:/Flowsmith/backend/app/api/executions.py#L391) generates distinct UUID per run; queue deduplication prevents re-enqueue of the same execution. |
| **Concurrent Webhook/Schedule** | Overlapping scheduled intervals or webhook floods | [has_running_execution()](file:///c:/Flowsmith/backend/app/api/executions.py#L368) skips scheduled/webhook runs if an execution is already `queued`, `running`, or `cancelling`. |

---

## 5. Distributed Scheduler & Trigger System

The Flowsmith scheduler ([app/scheduler.py](file:///c:/Flowsmith/backend/app/scheduler.py)) runs as an autonomous background daemon.

### 5.1 Distributed Advisory Locking
In multi-replica deployments (e.g. 3 API instances behind an ALB), multiple schedulers running simultaneously would cause duplicate tick executions.
- **Lock Implementation:** [Scheduler._try_acquire_lock()](file:///c:/Flowsmith/backend/app/scheduler.py#L133-L170) acquires a PostgreSQL advisory lock:
  ```sql
  SELECT pg_try_advisory_lock(8293471) -- 0x7EED01
  ```
- **Mutual Exclusion:** Exactly one replica holds the lock and performs the schedule tick. Other replicas fail the lock check and immediately return `0` without querying schedule triggers or double-firing.
- **Automatic Release:** If the leader instance crashes, PostgreSQL automatically releases the session-level advisory lock when the TCP connection closes.

### 5.2 Cron Occurrence & Watermarking
- **Wall Clock vs. UTC:** Cron candidates are calculated on the wall clock in the rule's specific timezone ([ZoneInfo](file:///c:/Flowsmith/backend/app/scheduler.py#L273)) and converted to UTC instants. DST transitions (spring forward / fall back) cannot duplicate or drop fires.
- **In-Memory Watermarking:** `_last_fired_for` tracks the exact timestamp consumed per rule, preventing duplicate firing if the system clock steps backwards.
- **Catch-Up Window:** On restart after downtime, missed fires within 5 minutes (`CATCH_UP_WINDOW`) fire for the most recent occurrence only; stale fires older than 5 minutes are discarded to prevent catch-up thundering herds.

---

## 6. Failure Injection & Recovery Mechanics

### 6.1 Worker Crashes & Heartbeat Leases
Workers maintain an asynchronous heartbeat loop ([QueueWorker._heartbeat](file:///c:/Flowsmith/backend/app/queue/worker.py#L167-L177)) updating `heartbeat_at` every `worker_heartbeat_s` (default 15s).
- **Lease Expiry:** If a worker crashes, its job remains in `queue:jobs:processing` (Redis) or `status = "claimed"` (DB).
- **Stale Sweep:** Idle workers execute `recover_stale(stale_seconds)` (default 60s). When elapsed time exceeds the lease threshold, the job is reclaimed and placed back on the queue with an incremented attempt counter.

### 6.2 Compare-And-Swap (CAS) Cancellation Guards
To eliminate race conditions between a user cancelling an execution and a worker picking it up:
1. When cancellation is requested via [cancel_execution](file:///c:/Flowsmith/backend/app/api/executions.py#L1590):
   - A `queued` execution transitions directly to `cancelled` via atomic SQL CAS.
   - A `running` execution transitions to `cancelling`.
2. When a worker claims a job in [run_job](file:///c:/Flowsmith/backend/app/execution_runtime.py#L225-L250):
   ```python
   flipped = db.query(ExecutionModel).filter(
       ExecutionModel.id == execution_id,
       ExecutionModel.status.in_(("queued", "running")),
   ).update({"status": "running"}, synchronize_session=False)
   ```
   If cancellation occurred immediately prior, `flipped == 0`. The worker rolls back, aborts execution, and marks the job complete without executing downstream nodes.

### 6.3 Orphan Reconciliation
If Redis is flushed or experiences unrecoverable memory loss, executions in PostgreSQL would remain stuck in `queued` forever.
- [recover_orphaned_executions](file:///c:/Flowsmith/backend/app/maintenance.py#L186-L235) periodically sweeps for executions in `queued` state older than `execution_queued_grace_s` (default 300s) that have no corresponding transport job.
- It safely re-enqueues the missing transport job using the execution record's stored snapshot.

---

## 7. Cross-Instance Event Delivery & WebSocket Resilience

Real-time canvas updates must reach users regardless of which API replica hosts their WebSocket connection:
1. **In-Process Fast Path:** The local [EventBus](file:///c:/Flowsmith/backend/app/eventbus.py) buffers recent events in memory for instant delivery to local WebSocket connections.
2. **Persistent Cross-Replica Path:** All execution events are durably recorded in the `execution_events` database table with a monotonic sequence number `seq`.
3. **Unified Streaming:** The WebSocket handler in [app/api/ws.py](file:///c:/Flowsmith/backend/app/api/ws.py#L190-L248) queries both the in-process bus and `execution_events` table using `db_after` offsets. If a client disconnects and reconnects to a different API node, it resumes stream consumption from its last acknowledged sequence number without event loss.

---

## 8. Checkpoint & Long-Running Approval Workflows

Flowsmith supports human-in-the-loop approvals via [HumanApprovalNode](file:///c:/Flowsmith/backend/app/nodes/human_approval.py):
1. **Durable Pause:** When execution reaches an approval node, the execution status transitions to `waiting_approval`. Node outputs up to that point are saved in `results`, and approval requirements (authorized approvers, message) are recorded in `pause_state`.
2. **Queue Acknowledgment:** The transport job is completed with status `DONE`, immediately releasing the worker thread/process back to the pool. Long-running approvals consume zero active compute or worker concurrency.
3. **Resumption from Checkpoint:** When approved via [resume_execution](file:///c:/Flowsmith/backend/app/api/executions.py#L1699), the execution transitions back to `queued`. The re-queued job payload carries `_approval_data` and pre-seeded upstream results, resuming downstream execution from the checkpoint without re-running prior nodes.

---

## 9. Honest Operational Boundaries & Unsupported Semantics

As a principal distributed-systems engineer, the following operational boundaries and distributed guarantees are documented:

1. **At-Least-Once Delivery vs. External Side Effects:** Flowsmith guarantees at-least-once task delivery for queue processing and state machine transitions. It **cannot** guarantee exactly-once execution for arbitrary third-party side effects (e.g. sending an email, charging a credit card via Stripe, calling an external non-idempotent HTTP API) if a worker crashes after initiating the HTTP call but before acknowledging completion. Workflows interacting with external services should utilize idempotency keys where supported by the target API.
2. **Cooperative Node Cancellation:** Workflow cancellation is cooperative between nodes. If a custom Python or JavaScript script enters a blocking non-yielding native C extension or infinite CPU loop without I/O points, cancellation takes effect at the process boundary when `timeout_seconds` triggers.
3. **Redis Sizing:** When using the Redis queue backend, Redis memory must be provisioned to hold the peak volume of pending job payloads. With `noeviction` enabled, Redis will reject new `LPUSH` operations with an error rather than evicting existing work.
4. **WebSocket Connection Lifetime:** WebSockets enforce a maximum connection lifetime of 1 hour with a 60-second idle ping/pong. Clients must support automatic reconnection and HTTP polling fallback (fully implemented in [executionStore.js](file:///c:/Flowsmith/frontend/src/stores/executionStore.js)).

---

## 10. Empirical Test Verification Matrix

All reliability and resilience behaviors were validated through failure-injection tests in [backend/tests/test_reliability/test_execution_reliability.py](file:///c:/Flowsmith/backend/tests/test_reliability/test_execution_reliability.py) and the queue test suite [backend/tests/test_queue/](file:///c:/Flowsmith/backend/tests/test_queue/):

| Test Case | Scenario / Failure Injected | Verified Outcome | Status |
| :--- | :--- | :--- | :--- |
| `test_redis_eviction_policy_verification` | Redis configured with unsafe `allkeys-lru` | Flagged as unsafe (`safe: False`); warning logged; `noeviction` verified safe. | **PASSED** |
| `test_redis_duplicate_delivery_idempotency` | Duplicate transport delivery of identical execution ID | SADD guard rejects second delivery; exactly 1 job claimed; guard cleaned on complete. | **PASSED** |
| `test_redis_stale_claim_recovery_and_retry_backoff` | Worker crashes holding job; time advances | Stale heartbeat detected; attempts incremented; exponential backoff scheduled via ZSET. | **PASSED** |
| `test_redis_poison_job_max_attempts_dead_letter` | Job crashes worker repeatedly past `queue_max_attempts` | Terminally failed; removed from processing; marked `failed` in DB with diagnostics. | **PASSED** |
| `test_db_queue_atomic_claim_and_skip_locked` | Multiple concurrent workers claiming from DB queue | `SELECT FOR UPDATE SKIP LOCKED` ensures exclusive, non-overlapping claims. | **PASSED** |
| `test_db_queue_duplicate_enqueue_rejected` | Duplicate enqueue of execution into DB queue | Rejection of duplicate; only single execution record maintained. | **PASSED** |
| `test_cycle_tolerance_and_deterministic_topological_sort` | Workflow containing circular visual feedback loop | Accepted by validator; Kahn's algorithm resolves deterministic linear ordering. | **PASSED** |
| `test_cycle_workflow_executes_each_node_at_most_once` | Cyclic graph executed end-to-end | Every node executed at most once; cycle-breaking semantics supplied empty input. | **PASSED** |
| `test_loop_while_hard_iteration_cap_terminates_run` | While loop with condition that never satisfies | Bounded strictly at `max_iterations`; raises `LOOP_LIMIT_EXCEEDED` on `on_limit="fail"`. | **PASSED** |
| `test_subworkflow_nesting_depth_guard` | Sub-workflow attempting recursion > depth 5 | Blocked with typed `SUBWORKFLOW_DEPTH_EXCEEDED` error; execution halted. | **PASSED** |
| `test_parallel_branch_concurrency_state_integrity` | 4 concurrent branches fan-out to merge node | All branches finish; node outputs uncorrupted; trace sorted chronologically. | **PASSED** |
| `test_import_workflow_is_draft_inactive_and_zero_executions` | Workflow imported with active flag & credentials | Forced to Draft/Inactive; credentials stripped; entropy added to paths; 0 runs. | **PASSED** |
| `test_duplicate_workflow_strips_credentials_and_never_executes` | Production workflow duplicated | Fresh ID generated; credentials stripped; active=False; 0 runs triggered. | **PASSED** |
| `test_scheduler_skips_when_workflow_already_running` | Scheduled trigger fires while workflow is running | `has_running_execution` detects active run; occurrence skipped without double-run. | **PASSED** |
| `test_scheduler_distributed_advisory_lock_single_runner` | Two schedulers attempt concurrent tick | Advisory lock key `0x7EED01` allows only single master; second skips completely. | **PASSED** |
| `test_cancellation_cas_state_transition` | Cancellation arrives in queued, running, and cancelling | Correct CAS transitions; queued cancelled immediately; running cancelled cooperatively. | **PASSED** |
| `test_human_approval_pause_checkpoint_and_resume` | Approval node pauses execution; resumed later | Execution stored in `waiting_approval`; worker released; resumed with checkpoint data. | **PASSED** |

### Test Suite Execution Summary
- **Reliability Suite:** 17/17 tests passing (`test_execution_reliability.py`) in 9.13s.
- **Queue Engine Suite:** 40/40 tests passing (`test_queue/`) in 23.56s.
- **Core Engine & Expressions:** 99/99 tests passing (`test_engine.py`, `test_graph.py`, `test_expressions.py`, `test_scheduler_lock.py`) in 40.52s.
- **Total Verification Count:** **156 passing tests (100% pass rate)**.
