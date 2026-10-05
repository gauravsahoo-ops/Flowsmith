"""Tests for OpenTelemetry Distributed Tracing Subsystem (Roadmap Initiative C)."""

import pytest
from app.telemetry.tracer import (
    clear_in_memory_spans,
    extract_trace_context,
    get_current_span_id,
    get_current_trace_id,
    get_in_memory_spans,
    get_tracer,
    init_tracer,
    inject_trace_context,
    start_trace_span,
)
from app.telemetry.flamegraph import generate_execution_flamegraph
from app.schemas.workflow import Workflow, WorkflowNode, Connection
from app.engine.executor import execute_workflow


def test_tracer_initialization_and_span_creation():
    clear_in_memory_spans()
    tracer = get_tracer("test.tracer")
    assert tracer is not None

    with start_trace_span("test.operation", attributes={"env": "test", "component": "unit_test"}) as span:
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()
        assert trace_id is not None
        assert len(trace_id) == 32
        assert span_id is not None
        assert len(span_id) == 16

    finished_spans = get_in_memory_spans()
    assert len(finished_spans) >= 1
    last_span = finished_spans[-1]
    assert last_span.name == "test.operation"
    assert last_span.attributes.get("env") == "test"
    assert "memory.delta_kb" in last_span.attributes


def test_w3c_trace_context_propagation():
    clear_in_memory_spans()

    carrier = {}
    with start_trace_span("parent.task") as parent_span:
        current_trace_id = get_current_trace_id()
        current_span_id = get_current_span_id()
        inject_trace_context(carrier)

        # W3C traceparent format: 00-{trace_id}-{span_id}-{trace_flags}
        assert "traceparent" in carrier
        parts = carrier["traceparent"].split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert parts[1] == current_trace_id
        assert parts[2] == current_span_id

    # Simulate receiving carrier on another service / worker
    extracted_ctx = extract_trace_context(carrier)
    assert extracted_ctx is not None

    with start_trace_span("child.worker_task", parent_context=extracted_ctx) as child_span:
        child_trace_id = get_current_trace_id()
        child_span_id = get_current_span_id()

        # Child must belong to the exact same distributed trace
        assert child_trace_id == current_trace_id
        assert child_span_id != current_span_id


def test_flamegraph_generation_from_steps():
    raw_steps = [
        {
            "node_id": "trigger_1",
            "node_type": "manual_trigger",
            "status": "success",
            "started_at": "2026-10-05T10:00:00.000000+00:00",
            "duration_ms": 25.5,
            "trace_id": "a" * 32,
            "span_id": "1" * 16,
            "memory_delta_kb": 12.4,
        },
        {
            "node_id": "http_1",
            "node_type": "http_request",
            "status": "success",
            "started_at": "2026-10-05T10:00:00.030000+00:00",
            "duration_ms": 150.0,
            "trace_id": "a" * 32,
            "span_id": "2" * 16,
            "memory_delta_kb": 34.0,
        },
        {
            "node_id": "code_1",
            "node_type": "code",
            "status": "success",
            "started_at": "2026-10-05T10:00:00.185000+00:00",
            "duration_ms": 14.5,
            "trace_id": "a" * 32,
            "span_id": "3" * 16,
            "memory_delta_kb": 4.2,
        },
    ]

    flamegraph = generate_execution_flamegraph(raw_steps)
    assert flamegraph["step_count"] == 3
    assert flamegraph["total_duration_ms"] > 150.0
    spans = flamegraph["spans"]
    assert len(spans) == 3

    assert spans[0]["node_id"] == "trigger_1"
    assert spans[0]["start_offset_ms"] == 0.0
    assert spans[0]["duration_ms"] == 25.5

    assert spans[1]["node_id"] == "http_1"
    assert spans[1]["start_offset_ms"] == 30.0
    assert spans[1]["duration_ms"] == 150.0

    assert spans[2]["node_id"] == "code_1"
    assert spans[2]["start_offset_ms"] == 185.0
    assert spans[2]["duration_ms"] == 14.5


@pytest.mark.asyncio
async def test_workflow_execution_records_trace_and_span_ids():
    clear_in_memory_spans()

    wf = Workflow(
        id="wf_telemetry_test",
        name="Telemetry Test Workflow",
        nodes=[
            WorkflowNode(id="n1", type="manual_trigger"),
            WorkflowNode(id="n2", type="set_variable", parameters={"assignments": [{"key": "status", "value": "ok"}]}),
        ],
        connections=[
            Connection(source="n1", target="n2"),
        ],
    )

    with start_trace_span("workflow.root_span") as root_span:
        root_trace_id = get_current_trace_id()
        result = await execute_workflow(wf, trigger_items=[{"input": 1}])

    assert result.status == "success"
    assert len(result.trace) >= 2

    for step in result.trace:
        # Every step in execution trace must have captured trace_id and span_id
        assert "trace_id" in step
        assert step["trace_id"] == root_trace_id
        assert "span_id" in step
        assert len(step["span_id"]) == 16


def test_opentelemetry_middleware_injects_headers():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    trace_id = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-Id")
    assert trace_id is not None
    assert len(trace_id) == 32
    assert "traceparent" in resp.headers
    assert trace_id in resp.headers["traceparent"]


def test_opentelemetry_middleware_preserves_incoming_traceparent():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    custom_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    custom_span_id = "00f067aa0ba902b7"
    incoming_traceparent = f"00-{custom_trace_id}-{custom_span_id}-01"

    resp = client.get("/api/health", headers={"traceparent": incoming_traceparent})
    assert resp.status_code == 200
    trace_id = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-Id")
    assert trace_id == custom_trace_id
    assert custom_trace_id in resp.headers.get("traceparent", "")

