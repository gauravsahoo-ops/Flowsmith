"""Minimal Prometheus-style metrics (Phase 7, no external dependency).

Hand-rolled counters/gauges/histograms rendered in the Prometheus text
format at `GET /api/metrics`. Thread-safe (executions finish on the
worker thread, HTTP middleware runs on the API loop). Live DB-derived
gauges (workflows, users) are resolved at scrape time.
"""

from __future__ import annotations

import time
from threading import Lock


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


class _Metric:
    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()) -> None:
        self.name = name
        self.help = help_text
        self.labels = labels
        self._lock = Lock()
        self._values: dict[str, float] = {}

    def _key(self, label_values: tuple[str, ...]) -> str:
        assert len(label_values) == len(self.labels)
        return ",".join(f'{k}="{v}"' for k, v in zip(self.labels, label_values))


class Counter(_Metric):
    def inc(self, label_values: tuple[str, ...] = (), amount: float = 1.0) -> None:
        key = self._key(label_values)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self._lock:
            for labels, value in sorted(self._values.items()):
                lines.append(f"{self.name}{{{labels}}} {_fmt(value)}")
        return "\n".join(lines)


class Gauge(_Metric):
    def set(self, value: float, label_values: tuple[str, ...] = ()) -> None:
        key = self._key(label_values)
        with self._lock:
            self._values[key] = value

    def inc(self, label_values: tuple[str, ...] = (), amount: float = 1.0) -> None:
        key = self._key(label_values)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, label_values: tuple[str, ...] = (), amount: float = 1.0) -> None:
        self.inc(label_values, -amount)

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        with self._lock:
            for labels, value in sorted(self._values.items()):
                lines.append(f"{self.name}{{{labels}}} {_fmt(value)}")
        return "\n".join(lines)


BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf"))


class Histogram(_Metric):
    """Cumulative buckets: name_bucket{le="x"} + name_sum + name_count."""

    def observe(self, value: float, label_values: tuple[str, ...] = ()) -> None:
        base = self._key(label_values)
        with self._lock:
            self._values[f"{base};sum"] = self._values.get(f"{base};sum", 0.0) + value
            self._values[f"{base};count"] = self._values.get(f"{base};count", 0.0) + 1
            for bucket in BUCKETS:
                if value <= bucket:
                    self._values[f"{base};{bucket}"] = self._values.get(f"{base};{bucket}", 0.0) + 1

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with self._lock:
            for key, value in sorted(self._values.items(), key=lambda kv: (kv[0].split(";")[0], float(kv[0].split(";")[1]) if kv[0].split(";")[1] not in ("sum", "count") else float("inf"))):
                labels, suffix = key.split(";", 1)
                if suffix in ("sum", "count"):
                    lines.append(f"{self.name}_{suffix}{{{labels}}} {_fmt(value)}")
                else:
                    le = "+Inf" if suffix == "inf" else _fmt(float(suffix))
                    lines.append(f'{self.name}_bucket{{{labels},le="{le}"}} {_fmt(value)}')
        return "\n".join(lines)


# ---- registered metrics -----------------------------------------------------

http_requests = Counter("http_requests_total", "HTTP requests handled", ("method", "path", "status"))
http_duration = Histogram("http_request_duration_seconds", "HTTP request duration", ("method", "path"))
executions_started = Counter("executions_started_total", "Executions queued", ("trigger",))
executions_finished = Counter("executions_finished_total", "Executions finished", ("status", "trigger"))
executions_running = Gauge("executions_running", "Executions currently running")
execution_duration = Histogram("execution_duration_seconds", "Execution wall time")
webhook_deliveries = Counter("webhook_deliveries_total", "Webhook deliveries", ("status",))
ratelimit_rejected = Counter("ratelimit_rejected_total", "Requests rejected by a rate limiter", ("scope",))
audit_events = Counter("audit_events_total", "Audit events recorded")

_STARTED_AT: dict[str, float] = {}
_start_lock = Lock()
_PROCESS_START = time.monotonic()


def execution_started(execution_id: str, trigger: str) -> None:
    executions_started.inc((trigger,))
    executions_running.inc()
    with _start_lock:
        _STARTED_AT[execution_id] = time.monotonic()


def execution_finished(execution_id: str, status: str, trigger: str) -> None:
    executions_finished.inc((status, trigger))
    executions_running.dec()
    with _start_lock:
        started = _STARTED_AT.pop(execution_id, None)
    if started is not None:
        execution_duration.observe(time.monotonic() - started)


def render_metrics(live: list[tuple[str, float]] | None = None) -> str:
    """Render every metric; `live` supplies DB-derived gauges as
    (name, value) pairs."""
    parts = [
        http_requests.render(),
        http_duration.render(),
        executions_started.render(),
        executions_finished.render(),
        execution_duration.render(),
        webhook_deliveries.render(),
        ratelimit_rejected.render(),
        audit_events.render(),
        executions_running.render(),
    ]
    for name, value in (live or []):
        parts.append(f"# HELP {name} {name}\n# TYPE {name} gauge\n{name} {_fmt(value)}")
    uptime = f"# HELP process_uptime_seconds Seconds since process start\n# TYPE process_uptime_seconds gauge\nprocess_uptime_seconds {_fmt(time.monotonic() - _PROCESS_START)}"
    parts.append(uptime)
    return "\n\n".join(parts) + "\n"
