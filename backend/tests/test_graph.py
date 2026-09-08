"""Graph validation tests (spec 24.3, 51.1)."""

from __future__ import annotations

import pytest

from app.engine.errors import WorkflowValidationError
from app.engine.graph import build_graph, topological_sort, validate_graph
from tests.conftest import conn, make_node, make_workflow


def test_empty_workflow_allowed():
    # Empty canvas is a valid notes scratchpad — no crash, no validation error
    # (user can delete all nodes and add notes/comments)
    validate_graph(make_workflow([]))
    # Should produce empty order and not raise
    order = topological_sort(build_graph(make_workflow([])))
    assert order == []


def test_duplicate_node_ids_rejected():
    wf = make_workflow([make_node("n1", "manual_trigger"), make_node("n1", "set_data")])
    with pytest.raises(WorkflowValidationError) as exc:
        validate_graph(wf)
    codes = [i["code"] for i in exc.value.issues]
    assert "DUPLICATE_NODE_ID" in codes


def test_unknown_node_type_rejected():
    wf = make_workflow([make_node("n1", "does_not_exist")])
    with pytest.raises(WorkflowValidationError) as exc:
        validate_graph(wf)
    assert exc.value.issues[0]["code"] == "UNKNOWN_NODE_TYPE"


def test_invalid_parameter_rejected():
    wf = make_workflow([make_node("n1", "http_request", parameters={"url": ""})])
    with pytest.raises(WorkflowValidationError) as exc:
        validate_graph(wf)
    assert exc.value.issues[0]["code"] == "INVALID_PARAMETER"


def test_dangling_connection_rejected():
    wf = make_workflow(
        [make_node("n1", "manual_trigger")],
        [conn("n1", "ghost")],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_graph(wf)
    codes = [i["code"] for i in exc.value.issues]
    assert "INVALID_CONNECTION" in codes


def test_invalid_output_handle_rejected():
    wf = make_workflow(
        [make_node("n1", "manual_trigger"), make_node("n2", "set_data")],
        [conn("n1", "n2", source_handle="nope")],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_graph(wf)
    assert exc.value.issues[0]["code"] == "INVALID_OUTPUT_HANDLE"


def test_cycle_tolerated():
    """Cycles in the graph topology are now allowed. The engine runs
    each node at most once per pass, so a cycle simply means the
    involved node is scheduled in topological order (any valid order)
    and the cycle edges are extra incoming dependencies for ordering.
    """
    wf = make_workflow(
        [make_node("n1", "set_data"), make_node("n2", "set_data")],
        [conn("n1", "n2"), conn("n2", "n1")],
    )
    # Must not raise; both nodes must appear in the produced order.
    order = topological_sort(build_graph(wf))
    assert set(order) == {"n1", "n2"}
    assert len(order) == 2


def test_self_loop_tolerated():
    """Self-loops are tolerated by the engine (the node still runs once).
    The frontend's `canConnect` rejects self-loops at draw time for UX,
    but the backend should not crash on a workflow that contains one
    (e.g. from an API client or an old saved draft)."""
    wf = make_workflow(
        [make_node("n1", "set_data")],
        [conn("n1", "n1")],
    )
    order = topological_sort(build_graph(wf))
    assert order == ["n1"]


def test_valid_workflow_passes():
    wf = make_workflow(
        [
            make_node("n1", "manual_trigger"),
            make_node("n2", "set_data", parameters={"fields": {"a": 1}}),
        ],
        [conn("n1", "n2")],
    )
    validate_graph(wf)
    order = topological_sort(build_graph(wf))
    assert order.index("n1") < order.index("n2")


def test_topological_order_respects_dependencies():
    wf = make_workflow(
        [make_node("n1", "set_data"), make_node("n2", "set_data"), make_node("n3", "set_data")],
        [conn("n1", "n3"), conn("n2", "n3")],
    )
    order = topological_sort(build_graph(wf))
    assert order.index("n3") > order.index("n1")
    assert order.index("n3") > order.index("n2")


def _setting_issues(wf):
    with pytest.raises(WorkflowValidationError) as exc:
        validate_graph(wf)
    return [i["code"] for i in exc.value.issues]


def test_invalid_merge_mode_rejected():
    wf = make_workflow(
        [make_node("n1", "set_data", settings={"merge_mode": "nope"})],
    )
    assert "INVALID_SETTING" in _setting_issues(wf)


def test_valid_merge_modes_accepted():
    for mode in ("wait_for_all", "wait_for_one", "combine"):
        wf = make_workflow(
            [make_node("n1", "set_data", settings={"merge_mode": mode})],
        )
        validate_graph(wf)


def test_invalid_retry_settings_rejected():
    wf = make_workflow(
        [make_node("n1", "set_data", settings={"retry_max_attempts": 50})],
    )
    assert "INVALID_SETTING" in _setting_issues(wf)

    wf = make_workflow(
        [make_node("n1", "set_data", settings={"retry_backoff_seconds": -1})],
    )
    assert "INVALID_SETTING" in _setting_issues(wf)


def test_invalid_workflow_settings_rejected():
    wf = make_workflow([make_node("n1", "set_data")], wf_id="wf_s")
    wf.settings["max_parallelism"] = 0
    assert "INVALID_SETTING" in _setting_issues(wf)

    wf = make_workflow([make_node("n1", "set_data")], wf_id="wf_s2")
    wf.settings["timeout_seconds"] = -3
    assert "INVALID_SETTING" in _setting_issues(wf)
