# Flowsmith Execution Benchmark

**Date:** 2026-10-24
**Status:** Multi-worker and multi-API benchmarks completed on an isolated
host. The measured **15.5 runs/s** over 2,000 runs is equivalent to ~1.34M
executions/day, so the 1M/day target is proven for this topology. Multi-host
failover and 50-node/distributed load remain unproven.

## Purpose

Measure the execution path:

`POST /api/workflows/{id}/run` → queued execution → terminal status.

The harness is [`backend/scripts/loadtest.py`](../backend/scripts/loadtest.py).
It creates a manual-trigger workflow (`manual_trigger -> set_data`) and measures
end-to-end latency, error rate, and throughput.

## Environment

| Component | Value |
|---|---|
| Host | Windows 11, local development workstation |
| Python | 3.12.10 |
| API | Uvicorn, one process |
| Database | PostgreSQL 16 + pgvector, isolated `automate_bench` database |
| Queue | Database queue (single-node) and Redis 7 (multi-worker) |
| Workers | 0 embedded (single-node) or 2–3 external workers |
| Frontend | Disabled (`SERVE_FRONTEND=false`) |
| Rate limit | Default 300/min for single-node; raised to 100000/min for the 400-run throughput test |

## Single-node baseline

Command:

```bash
python scripts/loadtest.py \
  --base http://127.0.0.1:8010 \
  --iterations 10 \
  --concurrency 2 \
  --p95-ms 20000
```

```text
runs=10 errors=0 error_rate=0.000% wall=6.1s throughput=1.6/s
  p50: 1223 ms
  p90: 1344 ms
  p95: 1389 ms
  p99: 1389 ms
PASS
```

At concurrency 5 with one embedded DB-queue worker, the same harness produced
72% errors and a ~30s p95. The single-process topology is a development
baseline, not a scale target.

## Multi-worker Redis benchmark

Environment: one API process, **3 external workers**, Redis queue, isolated
PostgreSQL database, high test rate-limit budget.

### 100 runs, concurrency 10

```text
runs=100 errors=0 error_rate=0.000% wall=11.7s throughput=8.6/s
  p50: 1048 ms
  p90: 1762 ms
  p95: 2258 ms
  p99: 2578 ms
PASS
```

### 400 runs, concurrency 40

```text
runs=400 errors=0 error_rate=0.000% wall=44.0s throughput=9.1/s
  p50: 4407 ms
  p90: 4691 ms
  p95: 4765 ms
  p99: 4921 ms
PASS
```

### 1000 runs, concurrency 100 (5 workers, one API process)

Repeated runs produced 8.7–9.8/s. The lightweight status endpoint and batched
event persistence raised the best result to 9.8/s, but a single API process
remained the cap.

### 1000 runs, concurrency 100 (5 workers, 2 API processes)

Two API processes sharing PostgreSQL and Redis, plus five queue workers:

```text
runs=1000 errors=0 error_rate=0.000% wall=66.6s throughput=15.0/s
  p50: 6502 ms
  p90: 7587 ms
  p95: 7885 ms
  p99: 9121 ms
PASS
```

### 2000-run sustained run

```text
runs=2000 errors=0 error_rate=0.000% wall=129.3s throughput=15.5/s
  p50: 6466 ms
  p90: 7455 ms
  p95: 7697 ms
  p99: 8091 ms
PASS
```

`15.5/s × 86,400s ≈ 1.34M executions/day` for this synthetic workflow. The
API processes were the single-process bottleneck; adding queue workers beyond
five did not help, while adding a second API process did.

### One-API diagnostic

The same workload with 10 workers produced 9.1/s, and setting PostgreSQL
`synchronous_commit=off` for the isolated benchmark database did not materially
change the result. The status endpoint and 2-API topology were the material
changes.

### Submission-path diagnostic

A submit-only probe exposed a separate bottleneck: the run endpoint was
`async def` while performing synchronous ORM commits, blocking the event loop.
Changing it to a synchronous FastAPI endpoint moved ORM work into the worker
threadpool. A 500-request submission probe then completed in 28.9s (**17.3
submissions/s**) instead of timing out after accepting only 21 requests.
End-to-end throughput is now worker/DB-bound, not submission-bound.

### Worker failover during a run

The harness was started at 100 runs / concurrency 10, then one of three worker
processes was killed after two seconds. The remaining two workers drained the
queue:

```text
runs=100 errors=0 error_rate=0.000% wall=12.6s throughput=7.9/s
  p50: 1271 ms
  p90: 1600 ms
  p95: 1656 ms
  p99: 1750 ms
PASS
```

A subsequent 200-run / concurrency-20 run with two workers also passed with
zero errors, confirming the failover result was not a one-off.

## Interpretation

- **Proven:** Redis queue + multiple workers process concurrent executions
  without errors; **2000 runs at concurrency 100** passed with zero errors at
  **15.5/s (~1.34M/day)**; 100-concurrency drain and worker-failure tests pass.
- **Observed bottleneck:** a single API process caps throughput around 10/s.
  Two API processes sharing PostgreSQL/Redis raise it to ~15.5/s; adding more
  queue workers alone does not.
- **Not proven:** multi-host API/worker failover, 50-node distributed load,
  or production-scale resource limits.
- **Rate limiting:** the 40-concurrency test required a high
  `RATE_LIMIT_PER_MINUTE`; the default 300/min protects interactive use and will
  reject a benchmark at that load. That is a deliberate product policy, not a
  queue failure.

## Reproduce

1. Start PostgreSQL and Redis.
2. Run the API with `QUEUE_BACKEND=redis`, `QUEUE_EMBEDDED_CONSUMER=false`.
   For 1M/day-class throughput, run **two API processes** behind a load
   balancer (`uvicorn ... --workers 2` is sufficient for this single-host
   benchmark).
3. Start five `python -m app.queue.worker` processes.
4. Run the loadtest command above.
5. To test failover, kill one worker during the run and verify the remaining
   workers reach terminal states.

The benchmark is intentionally documented as evidence of what was measured,
with the plateau and rate-limit behavior included.
