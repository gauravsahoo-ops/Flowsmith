# Flowsmith Execution Engine & Runtime Specifications

**Version:** 1.0.0 Enterprise  
**Core Runtime:** Python 3.12+ AsyncIO + Subprocess Sandboxing + Redis Task Distribution  
**Key Guarantees:** Topological Soundness, Cycle Prevention, Parallel Fan-Out, Step Idempotency, Multi-Tier Recovery

---

## 1. Engine Topology & Graph Compilation

Flowsmith executes workflows as Directed Acyclic Graphs (DAGs). The workflow document contains a set of `nodes` and directional `edges`:

```
                 ┌───────────────┐
                 │ Webhook Node  │
                 └───────┬───────┘
                         │
                 ┌───────▼───────┐
                 │ Filter Node   │
                 └───────┬───────┘
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
     ┌───────────────┐       ┌───────────────┐
     │ Branch A (CRM)│       │ Branch B (AI) │
     └───────┬───────┘       └───────┬───────┘
             │                       │
             └───────────┬───────────┘
                         ▼
                 ┌───────────────┐
                 │ Slack Alert   │
                 └───────────────┘
```

### Graph Compilation (`app.engine.graph`)

1. **In-Memory Dependency Graph**:
   - Compiles node IDs and directed edges into an adjacency list with in-degree tracking.
2. **Cycle Detection (Kahn's Algorithm)**:
   - Evaluates graph connectivity. If any circular reference is detected, compilation halts immediately with a descriptive `CycleError`, indicating the exact loop cycle.
3. **Branching & Condition Propagation**:
   - Conditional nodes (`if`, `switch`, `filter`) select output handles (`true`, `false`, `default`).
   - The scheduler dynamically deactivates downstream branches originating from unselected handles, preventing deadlocks at downstream merge points.

---

## 2. Concurrency & Parallel Execution Model

The engine operates on a high-throughput **AsyncIO event loop** (`app.engine.executor`):

- **Parallel Fan-Out**:
  - When a node has multiple outgoing edges, child branches are gathered and executed concurrently using `asyncio.gather(*tasks, return_exceptions=True)`.
- **Merge & Synchronization**:
  - Merge nodes wait until all active ancestor branches complete before proceeding.
  - Inactive branches (pruned by condition evaluations) are treated as resolved skips, allowing the merge node to proceed without waiting indefinitely.
- **I/O Bound Operations**:
  - All outbound network calls (HTTP, Redis, PostgreSQL) use native non-blocking async drivers (`httpx`, `asyncpg`, `redis-py`).
- **CPU Bound & Sandboxed Operations**:
  - Python and JavaScript code nodes are dispatched to dedicated worker subprocesses to prevent blocking the async event loop.

---

## 3. Node Execution Lifecycle & State Machine

Each node transitions through a deterministic state machine:

```
                  ┌─────────────┐
                  │   PENDING   │
                  └──────┬──────┘
                         │ (Scheduler Dispatches)
                         ▼
                  ┌─────────────┐
                  │   RUNNING   │
                  └──────┬──────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
 ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
 │   SUCCESS   │  │   WAITING   │  │    ERROR    │
 └─────────────┘  └──────┬──────┘  └──────┬──────┘
                         │                │
                         │ (Resume Signal)│ (Retry Exceeded)
                         ▼                ▼
                  ┌─────────────┐  ┌─────────────┐
                  │   RUNNING   │  │ ERROR RECOVERY
                  └─────────────┘  └─────────────┘
```

### State Definitions
- **`pending`**: Node is waiting for upstream ancestor nodes to finish.
- **`running`**: Node parameters are evaluated, expressions resolved, and logic executing.
- **`waiting`**: Node requested long-running suspension (`wait` delay or `approval` request). State serialized to PostgreSQL.
- **`success`**: Step completed. Output payload committed to execution context. Downstream nodes unblocked.
- **`error`**: Step failed. Handled via node retry policies or escalated to multi-level error workflows.

---

## 4. Expression & Templating Engine

Flowsmith provides an intuitive expression resolution syntax:

| Syntax | Description | Example |
| :--- | :--- | :--- |
| `{{ $json.field }}` | Direct upstream node output payload | `{{ $json.user.email }}` |
| `{{ $node["NodeName"].json }}`| Specific named ancestor node payload | `{{ $node["Stripe Hook"].json.amount }}` |
| `{{ $env.VAR_NAME }}` | Environment variables / Workspace settings | `{{ $env.SALESFORCE_INSTANCE_URL }}` |
| `{{ $execution.id }}` | Current execution runtime metadata | `{{ $execution.id }}` |
| `{{ new Date().toISOString() }}`| JavaScript expressions & built-in utilities | `{{ $json.price * 1.15 }}` |

Expressions are safely evaluated without `eval()` using a secure AST expression parser.

---

## 5. Long-Running Executions & Suspension

For processes spanning minutes, days, or weeks (e.g. "Wait 3 days before follow-up" or "Wait for VP approval"):

1. **State Serialization**:
   - The engine serializes the complete in-flight execution context, variable scope, and node outputs into PostgreSQL.
   - The worker process releases memory and returns to the pool immediately.
2. **Wake-Up Dispatchers**:
   - **Time-based (`wait` node)**: Registered in `schedule_triggers` table. Evaluated by the cron scheduler.
   - **Event-based (`approval` node / webhook callback)**: Awaits an incoming signed POST request to `/api/approvals/{token}` or `/api/executions/{id}/resume`.
3. **Atomic Resumption**:
   - Upon trigger, the execution state is reloaded from PostgreSQL, and downstream nodes resume execution from the exact point of suspension.

---

## 6. Multi-Level Error Recovery Architecture

```
                  ┌──────────────────────┐
                  │ Node Throws Exception│
                  └──────────┬───────────┘
                             │
                  ┌──────────▼───────────┐
                  │ Node Retry Policy?   │──(Yes, Retries Left)──> Backoff & Retry
                  └──────────┬───────────┘
                             │ (No / Exhausted)
                  ┌──────────▼───────────┐
                  │ Continue on Fail?    │──(Yes)──> Route to Error Branch Handle
                  └──────────┬───────────┘
                             │ (No)
                  ┌──────────▼──────────────────────────┐
                  │ Workflow "on_error_workflow_id" set?│──(Yes)──> Execute Workflow Error Handler
                  └──────────┬──────────────────────────┘
                             │ (No)
                  ┌──────────▼──────────────────────────┐
                  │ Active Workspace "error_trigger"?   │──(Yes)──> Execute Workspace Error Handler
                  └──────────┬──────────────────────────┘
                             │ (No)
                  ┌──────────▼───────────┐
                  │ Route to System DLQ  │──> Persist to Dead Letter Queue for Operator Inspection
                  └──────────────────────┘
```

1. **Node Retry with Jitter**: Configurable attempts (1–5), exponential backoff base, and decorrelated random jitter to prevent thundering herds on external services.
2. **Workflow-Level Error Workflow**: Invokes a designated workflow passing failure payload (`error.message`, `error.node_id`, `execution.id`).
3. **Workspace-Level Global Error Catch**: Any active workflow containing an `error_trigger` node acts as a workspace-wide safety net.
4. **Dead Letter Queue (DLQ)**: Failed executions are archived in `dead_letter_jobs` with full stack traces, allowing 1-click manual re-run once the root cause is resolved.

---

## 7. Data Pinning & Live Step Execution

- **Data Pinning**:
  - Developers can freeze real production payloads on any node (`settings.pinned_data`).
  - During development, testing child nodes runs against the pinned data instantly, eliminating the need to trigger upstream third-party webhooks repeatedly.
- **In-Context Live Step Execution (`POST /api/nodes/test-step`)**:
  - Runs an isolated single node in the cloud backend.
  - Automatically resolves upstream ancestor data.
  - Emits real HTTP responses, schema validations, and execution durations in under 200ms.
