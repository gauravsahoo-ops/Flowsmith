# Monitoring & Ops (Phase 7)

## Metrics

`GET /api/metrics` exposes Prometheus text format (no external
dependency). Scrape it with Prometheus:

```yaml
scrape_configs:
  - job_name: automation
    metrics_path: /api/metrics
    static_configs:
      - targets: ["127.0.0.1:8000"]
```

Available series:

| Metric                              | Type      | Meaning                              |
| ----------------------------------- | --------- | ------------------------------------ |
| `http_requests_total{method,path,status}` | counter | HTTP requests (path = route template) |
| `http_request_duration_seconds{method,path}` | histogram | request duration                  |
| `executions_started_total{trigger}` | counter   | executions queued (manual/webhook/schedule/retry) |
| `executions_finished_total{status,trigger}` | counter | execution outcomes            |
| `executions_running`                | gauge     | executions currently running         |
| `execution_duration_seconds`        | histogram | execution wall time                  |
| `webhook_deliveries_total{status}`  | counter   | queued vs skipped deliveries         |
| `ratelimit_rejected_total{scope}`   | counter   | 429s (login vs webhook)              |
| `audit_events_total`                | counter   | audit events recorded                |
| `workflows_total` / `users_total`   | gauge     | DB counts at scrape time             |
| `process_uptime_seconds`            | gauge     | process uptime                       |

Security: the endpoint is unauthenticated (like the health check) so
Prometheus can scrape it without tokens. **Protect it** in production
with a firewall or a separate scrape-only network; never expose it to
the public internet.

Useful alerts: `executions_finished_total{status="failed"}`
rate > 0 over 5m, `executions_running` sustained above N,
`ratelimit_rejected_total` rate spikes, and `process_uptime_seconds`
resetting (restart loop).

## Structured logging

`python -m app.serve` enables JSON logging (one object per line):

```json
{"ts":"2026-08-12T11:00:00+00:00","level":"INFO","logger":"app.request","msg":"request POST /api/webhooks/x -> 202","fields":{"method":"POST","path":"/api/webhooks/x","status":202,"duration_ms":3.2}}
```

- `LOG_FORMAT=json` (default) or `plain` for human-readable output.
- `LOG_LEVEL=INFO` (default) controls verbosity.
- Every HTTP request logs method/path/status/duration — never headers,
  bodies or tokens. Credential payloads are never logged anywhere.
- uvicorn access/error logs are JSON too (root handler owns them).

In Docker: `docker compose logs -f` shows JSON lines; forward them to
your log aggregator as-is.

## Health checks

`GET /api/health` returns status, version, `public_url`, `uptime_s`
and a live DB check (`database: "ok" | "error"`). The container
healthcheck (Dockerfile) uses it.

## Uptime & monitoring workflows

Beyond scraping, you can build **monitoring into the product itself**:
a schedule-triggered workflow can hit `/api/health` (http_request
node) and send an email / post a webhook when `database` is not `ok`
or `status` is not `ok`.

## Known limits (single worker)

Metrics are in-process counters — with multiple workers each serves
its own counters from its own `/api/metrics`; point Prometheus at each
replica (or add an external collector). Rate-limit state is likewise
per-process (see `docs/security.md`).
