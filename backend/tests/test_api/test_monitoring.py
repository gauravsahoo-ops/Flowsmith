"""Phase 7 tests: structured request logging side effects, metrics
endpoint, health uptime, metric instrumentation of executions."""

from __future__ import annotations

import logging
import re
import time

from tests.test_api.conftest import auth_headers, make_workflow, register


def _metric_value(text: str, name: str, *label_pairs: tuple[str, str]) -> int | float | None:
    labels = ",".join(f'{k}="{v}"' for k, v in label_pairs)
    pattern = rf"^{re.escape(name)}(\{{(?:[^{{}}]*?{re.escape(labels)}[^{{}}]*?)\}})? (\d+(?:\.\d+)?)$"
    for line in text.splitlines():
        m = re.match(pattern, line)
        if m and ("{" not in m.group(1) or label_pairs):
            try:
                return float(m.group(2))
            except ValueError:
                return None
    return None


def test_metrics_endpoint_requires_auth(client):
    # Phase 23/38: metrics is no longer anonymous (per-route traffic
    # volumes aid recon); scrapers authenticate with a service token.
    assert client.get("/api/metrics").status_code in (401, 403)


def test_metrics_endpoint_is_prometheus_format(client):
    reg = register(client)
    resp = client.get("/api/metrics", headers=auth_headers(reg["token"]))
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    text = resp.text
    assert "# HELP http_requests_total" in text
    assert "# TYPE http_requests_total counter" in text
    assert "# HELP process_uptime_seconds" in text
    assert "# TYPE process_uptime_seconds gauge" in text


def test_metrics_endpoint_accepts_query_token(client):
    reg = register(client)
    resp = client.get(f"/api/metrics?token={reg['token']}")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "# HELP http_requests_total" in resp.text


def test_metrics_include_db_gauges_and_request_counter(client):
    reg = register(client)
    resp = client.get("/api/metrics", headers=auth_headers(reg["token"]))
    text = resp.text
    assert "workflows_total 0" in text
    value = _metric_value(text, "http_requests_total", ("method", "GET"), ("path", "/api/metrics"), ("status", "200"))
    assert value is not None and value >= 1


def test_health_reports_uptime_and_database(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["database"] == "ok"
    assert isinstance(data["uptime_s"], int) and data["uptime_s"] >= 0
    assert data["version"]


def _await_finished(client, headers, exec_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/executions/{exec_id}", headers=headers).json()["data"]["status"]
        if status not in ("running", "queued", "cancelling"):
            return status
        time.sleep(0.1)
    raise AssertionError(f"execution {exec_id} did not finish")


def test_executions_are_instrumented(client):
    reg = register(client)
    wf = make_workflow()
    client.post("/api/workflows", json=wf, headers=auth_headers(reg["token"]))
    run = client.post(f"/api/workflows/{wf['id']}/run", json={}, headers=auth_headers(reg["token"]))
    assert run.status_code == 202
    exec_id = run.json()["data"]["execution_id"]
    assert _await_finished(client, auth_headers(reg["token"]), exec_id) == "success"

    text = client.get("/api/metrics", headers=auth_headers(reg["token"])).text
    started = _metric_value(text, "executions_started_total", ("trigger", "manual"))
    assert started is not None and started >= 1
    finished = _metric_value(text, "executions_finished_total", ("status", "success"), ("trigger", "manual"))
    assert finished is not None and finished >= 1
    assert "# TYPE execution_duration_seconds histogram" in text


def test_request_log_line_emitted(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.request"):
        client.get("/api/health")
    assert any("request GET /api/health -> 200" in r.getMessage() for r in caplog.records)
    assert any(r.fields["status"] == 200 and "duration_ms" in r.fields for r in caplog.records)


def test_monitoring_stats_accessible_by_standard_user(client):
    reg = register(client)
    resp = client.get("/api/monitoring/stats", headers=auth_headers(reg["token"]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "workflows" in data
    assert "executions" in data
    assert "uptime_seconds" in data
    assert "last_hour" in data