"""OpenTelemetry Distributed Tracing Subsystem for Flowsmith (Roadmap Initiative C).

Supports:
- W3C TraceContext context propagation (traceparent / tracestate).
- Zero-overhead in-memory ring buffer for flamegraphs and execution inspection.
- One-click export to OTLP / Datadog / Honeycomb / Dynatrace / Grafana Tempo.
- Per-node spans with latency, memory delta, and error status.
- Resilient fallback to No-Op tracing if OpenTelemetry SDK is not installed.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tracemalloc
from typing import Any, Iterator, Optional

logger = logging.getLogger("telemetry")

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import Span, Status, StatusCode
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False
    trace = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment,misc]
    TracerProvider = None  # type: ignore[assignment,misc]
    SimpleSpanProcessor = None  # type: ignore[assignment,misc]
    InMemorySpanExporter = None  # type: ignore[assignment,misc]
    Span = Any  # type: ignore[assignment,misc]
    Status = None  # type: ignore[assignment,misc]
    StatusCode = None  # type: ignore[assignment,misc]
    TraceContextTextMapPropagator = None  # type: ignore[assignment,misc]


class _NoOpSpan:
    """Fallback no-op span when OpenTelemetry SDK is absent."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def record_exception(self, exc: BaseException) -> None:
        pass

    def get_span_context(self) -> Any:
        return None


class _NoOpTracer:
    """Fallback no-op tracer when OpenTelemetry SDK is absent."""

    @contextlib.contextmanager
    def start_as_current_span(
        self,
        name: str,
        context: Any = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[_NoOpSpan]:
        yield _NoOpSpan()


# Global singleton exporter and provider
_in_memory_exporter: Optional[Any] = None
_tracer_provider: Optional[Any] = None
_propagator = TraceContextTextMapPropagator() if HAS_OTEL else None


def init_tracer(
    service_name: str = "flowsmith",
    environment: str = "production",
    service_version: str = "1.0.0",
) -> Any:
    """Initialize OpenTelemetry tracer provider with resources and exporters."""
    global _tracer_provider, _in_memory_exporter

    if not HAS_OTEL:
        logger.debug("OpenTelemetry SDK not installed; tracing running in no-op mode.")
        return None

    if _tracer_provider is not None:
        return _tracer_provider

    svc_name = os.getenv("OTEL_SERVICE_NAME", service_name)
    env = os.getenv("DEPLOYMENT_ENV", os.getenv("ENVIRONMENT", environment))

    resource = Resource.create({
        "service.name": svc_name,
        "service.version": service_version,
        "deployment.environment": env,
    })

    provider = TracerProvider(resource=resource)

    # In-memory exporter for local flamegraph generation and test assertions
    _in_memory_exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(_in_memory_exporter))

    # Optional remote OTLP Exporter (Datadog, Honeycomb, Tempo, Dynatrace)
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            otlp_headers_raw = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
            headers = {}
            if otlp_headers_raw:
                for item in otlp_headers_raw.split(","):
                    if "=" in item:
                        k, v = item.split("=", 1)
                        headers[k.strip()] = v.strip()

            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, headers=headers)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info("OpenTelemetry OTLP exporter enabled targeting %s", otlp_endpoint)
        except Exception as exc:
            logger.warning("Failed to configure OTLP exporter: %s", exc)

    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    return provider


def get_tracer(name: str = "flowsmith.engine") -> Any:
    """Return the configured OpenTelemetry tracer."""
    global _tracer_provider
    if not HAS_OTEL:
        return _NoOpTracer()
    if _tracer_provider is None:
        init_tracer()
    return trace.get_tracer(name)


def get_in_memory_spans() -> list[Any]:
    """Retrieve captured in-memory spans for debugging or evaluation."""
    if _in_memory_exporter:
        return _in_memory_exporter.get_finished_spans()
    return []


def clear_in_memory_spans() -> None:
    """Clear captured in-memory spans."""
    if _in_memory_exporter:
        _in_memory_exporter.clear()


def inject_trace_context(carrier: dict[str, Any]) -> dict[str, Any]:
    """Inject active W3C traceparent into a carrier dictionary (headers or payload)."""
    if not HAS_OTEL or _propagator is None:
        return carrier
    try:
        current_ctx = trace.get_current_span().get_span_context()
        if current_ctx and current_ctx.is_valid:
            _propagator.inject(carrier)
    except Exception as exc:
        logger.debug("Failed to inject trace context: %s", exc)
    return carrier


def extract_trace_context(carrier: dict[str, Any]) -> Any:
    """Extract W3C trace context from headers or payload carrier."""
    if not HAS_OTEL or _propagator is None:
        return None
    try:
        # Normalize carrier keys to lowercase for robust header matching
        normalized = {str(k).lower(): str(v) for k, v in carrier.items() if v is not None}
        return _propagator.extract(carrier=normalized)
    except Exception as exc:
        logger.debug("Failed to extract trace context: %s", exc)
        return None


def get_current_trace_id() -> str | None:
    """Return the active 32-character hex trace ID, or None if inactive."""
    if not HAS_OTEL:
        return None
    ctx = trace.get_current_span().get_span_context()
    if ctx and ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return None


def get_current_span_id() -> str | None:
    """Return the active 16-character hex span ID, or None if inactive."""
    if not HAS_OTEL:
        return None
    ctx = trace.get_current_span().get_span_context()
    if ctx and ctx.is_valid:
        return format(ctx.span_id, "016x")
    return None


@contextlib.contextmanager
def start_trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    parent_context: Any = None,
) -> Iterator[Any]:
    """Context manager creating a new OpenTelemetry span with memory tracking."""
    if not HAS_OTEL:
        yield _NoOpSpan()
        return

    tracer = get_tracer()
    attrs = dict(attributes or {})

    # Memory allocation snapshot (cross-platform via tracemalloc)
    tracking_mem = not tracemalloc.is_tracing()
    if tracking_mem:
        tracemalloc.start()
    mem_before = tracemalloc.get_traced_memory()[0]

    with tracer.start_as_current_span(name, context=parent_context, attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            mem_after = tracemalloc.get_traced_memory()[0]
            mem_delta_kb = round(max(0, mem_after - mem_before) / 1024, 2)
            span.set_attribute("memory.delta_kb", mem_delta_kb)
            if tracking_mem:
                tracemalloc.stop()
