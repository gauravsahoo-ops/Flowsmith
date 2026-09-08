# Phase 9 — Parallel execution engine (spec 8.2)

> **Milestone:** independent branches run concurrently; merge modes,
> retries with backoff, per-run global timeout, coordinated failure
> handling. Replaces the sequential engine inherited from M1.
> **Status:** done — `tests/test_parallel.py` (11 tests) +
> `tests/test_engine.py` + `tests/test_graph.py` green.

## 1. What Phase 9 delivers

```text
            ┌─────────────── trigger ───────────────┐
            ▼                                       ▼
        branch A (0.4s)                        branch B (0.4s)   ← concurrent
            └───────────────┬───────────────────────┘
                            ▼
                      merge (default wait_for_all,
                             optional wait_for_one)
```

- **Ready-set scheduler** (`engine/executor.py`): every runnable node is
  an `asyncio.Task`; a run loop `await asyncio.wait(..., FIRST_COMPLETED)`
  wakes on each completion and schedules newly-ready children. A
  semaphore enforces `max_parallelism` (default 8).
- **Merge modes** (`engine/graph.py` → `node.settings.merge_mode`):
  `wait_for_all` — a node starts after **every** parent finished (default,
  and what the sequential engine did); `wait_for_one` — starts on the
  **first** parent (branch-level fan-in).
- **Retry policy** (spec 8.3): `retry_max_attempts`, exponential backoff
  `retry_backoff_seconds` (capped at `MAX_RETRY_BACKOFF_S`), only
  retryable errors retry (`NodeExecutionError(retryable=True)`); emits
  `node.retry` events with attempt/delay; the trace records the final
  attempt plus a note ("Failed 4 attempt(s); 3 failed retries…").
- **Failure semantics in parallel mode**: a failed branch pre-skips only
  descendants whose *every* parent failed — a sibling-parented merge
  still runs; `continue_on_error` keeps the run alive and forwards a
  `$error` item downstream. Node/AI timeouts and the global
  `workflow_timeout_s` cancel via the shared cancel event, and the
  run loop marks never-reachable nodes `skipped`.
- **Sibling isolation**: a failure on one branch never poisons an
  independent branch (tested).

## 2. Why it took the shape it did (bugs found on the way)

1. **Exceptions escaping the task vanish** — the sequential engine ran
   `_run_one` inside a guarded try; the new per-node tasks had no guard,
   so a credential error raised *before* `_run_one`'s retry loop (the
   `credential_resolver` call at the top) became an unhandled task
   exception and the run ended `success` with a leaked "Task exception
   was never retrieved". Fix: `run_one` wraps `_run_one` and calls
   `_fail` on both `NodeExecutionError` and any raw `Exception`.
2. **Wall-clock timing tests are flaky, the scheduler wasn't** — an
   "elapsed < 0.7s" assertion failed at 2.06s intermittently; isolating
   it showed the two 0.4s branches *did* overlap (0.469s) and the 2.06s
   was `httpx.AsyncClient()` construction (1.5s of TLS context setup on
   this machine), not the engine. The timing tests now prove parallelism
   from step timestamps in the trace (b started before a finished /
   merge started before the slow parent ended) — immune to slow machines.
3. **The retry stub couldn't pass** — a stub that always failed proved
   the retry loop worked but could never produce "succeeds after N
   attempts"; it now counts attempts per execution id.

## 3. Files

```text
backend/app/engine/
├── executor.py   # ready-set scheduling, retries, timeouts, merge modes
└── graph.py      # validate/merge_mode (wait_for_all | wait_for_one), topo

backend/tests/
├── test_parallel.py              # 11 tests: concurrency, merges, retries,
│                                 #   sibling isolation, timeout, pruning of
│                                 #   unreachable nodes
├── test_engine.py                # pre-existing sequential coverage (status)
└── test_graph.py                 # graph validation incl. merge-mode rules
```

## 4. Verification

- `pytest tests/test_parallel.py tests/test_engine.py tests/test_graph.py` —
  36 passed; full suite 210 passed; pyright clean.
- Behaviours proven: two 0.4s branches overlap in timestamps; a
  `wait_for_one` merge starts before its slow parent finishes; a
  `wait_for_all` merge starts exactly at the slow parent's end;
  `retry_max_attempts=3` yields 4 attempts (1 + 3 retries) with
  exponential backoff; a `boom` sibling leaves the other branch green;
  the 10s slow node with `workflow_timeout_s=0.15` cancels the run.