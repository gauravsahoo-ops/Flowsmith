# Phase 7 — Production ops: metrics, logging, health (M9)

> **Milestone:** run this thing outside a laptop — Prometheus-style
> metrics, structured JSON logs, health/uptime probes (spec 15, 17).
> **Status:** done, verified with API tests + a live Grafana-less
> Prometheus scrape of `GET /api/metrics`; docs in `docs/monitoring.md`.

*Came right after the unnumbered security phase (roles, sharing, audit,
throttling, credential key rotation — `docs/security.md`).*

## 1. What Phase 7 delivers

```text
request ─▶ MetricsMiddleware ─▶ /api/metrics (Prometheus text format)
            │  http_requests_total, http_request_duration_seconds
            ▼
        one structured JSON log line per request
                                                      GET /api/health
        executions ─▶ executions_started/finished_total,   ↑
                      executions_running, duration           uptime_s
                                                             + DB probe
```

- **`GET /api/metrics`** (`app/metrics.py`): zero-dependency counters,
  gauges and histograms rendered in the Prometheus text format, with
  labels for method/path/status (HTTP), trigger and status (executions),
  webhook delivery outcome, rate-limit rejections, audit events.
  Live gauges (workflows, users, running executions) are resolved at
  scrape time; a process-start uptime gauge rides along.
- **`GET /api/health`**: `{status: ok, uptime_s, version}` plus a live
  DB probe (SELECT 1) — the docker-compose healthcheck in the initial
  commit uses it.
- **Structured logging** (`app/logging_setup.py`): `LOG_FORMAT=json`
  (production default) → one JSON object per line (timestamp, level,
  logger, message + extra fields), `LOG_LEVEL` controls verbosity;
  plain human format in dev. A `MetricsMiddleware` adds one request log
  line with method/path/status/duration_ms.
- **Execution metrics wiring**: `execution_started/finished` hooks in
  `api/executions.py` and the webhook endpoint, so every trigger (manual,
  webhook, schedule, retry) shows up in metrics.

## 2. Why it took the shape it did

1. **No extra dependencies** — a hand-rolled ~150-line metrics module
   beats pulling in `prometheus-client` for a single-worker v1; the text
   format is trivial to render and scrape.
2. **Thread safety matters here**: middleware runs on the API loop while
   executions finish on the worker thread, so counters use a lock
   (`Counter.inc` is atomic) and the running-execution gauge is derived
   in `execution_started/finished` rather than stored mutable state.

## 3. Files

```text
backend/app/
├── metrics.py            # Counter/Gauge/Histogram + render_metrics()
├── logging_setup.py      # JSON formatter, LOG_FORMAT/LOG_LEVEL
├── main.py               # MetricsMiddleware, /api/health, /api/metrics
├── api/executions.py     # execution_started/finished hooks
└── api/webhooks.py       # webhook_deliveries metric

backend/tests/test_api/test_monitoring.py   # metrics shape, health, uptime
docs/monitoring.md                          # metrics, logging, health, limits
```

## 4. Verification

- `pytest tests/test_api/test_monitoring.py` — metrics endpoint returns
  Prometheus text with expected series/labels; health returns ok and a
  rising uptime; DB probe present.
- Live: start the app, `curl localhost:8000/api/metrics` shows
  `http_requests_total{method="GET",path="/api/metrics",status="200"}`;
  `curl localhost:8000/api/health` reports `status=ok`.