"""Flamegraph and Waterfall Trace Generator (Roadmap Initiative C).

Converts per-step execution trace records into a structured waterfall/flamegraph
data structure for the frontend execution inspector.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def generate_execution_flamegraph(trace_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse chronological execution trace steps into a flamegraph model.

    Computes:
    - total_duration_ms
    - relative_start_ms per node
    - memory_delta_kb (if recorded)
    - hierarchical visual spans
    """
    if not trace_records:
        return {
            "total_duration_ms": 0.0,
            "step_count": 0,
            "spans": [],
        }

    # Sort chronologically by start timestamp
    sorted_steps = sorted(
        trace_records,
        key=lambda s: s.get("started_at") or "",
    )

    first_iso = sorted_steps[0].get("started_at")
    try:
        base_time = datetime.fromisoformat(first_iso) if first_iso else None
    except Exception:
        base_time = None

    spans: list[dict[str, Any]] = []
    max_end_offset = 0.0

    for step in sorted_steps:
        started_iso = step.get("started_at")
        duration = float(step.get("duration_ms") or 0.0)

        # Compute relative start offset in milliseconds
        start_offset_ms = 0.0
        if base_time and started_iso:
            try:
                curr_time = datetime.fromisoformat(started_iso)
                start_offset_ms = max(0.0, (curr_time - base_time).total_seconds() * 1000)
            except Exception:
                start_offset_ms = 0.0

        end_offset_ms = start_offset_ms + duration
        if end_offset_ms > max_end_offset:
            max_end_offset = end_offset_ms

        spans.append({
            "node_id": step.get("node_id"),
            "node_type": step.get("node_type"),
            "status": step.get("status", "success"),
            "start_offset_ms": round(start_offset_ms, 2),
            "duration_ms": round(duration, 2),
            "end_offset_ms": round(end_offset_ms, 2),
            "attempts": step.get("attempts", 1),
            "retries": step.get("retries", 0),
            "trace_id": step.get("trace_id"),
            "span_id": step.get("span_id"),
            "memory_delta_kb": step.get("memory_delta_kb", 0.0),
            "error": step.get("error"),
        })

    return {
        "total_duration_ms": round(max_end_offset, 2),
        "step_count": len(spans),
        "spans": spans,
    }
