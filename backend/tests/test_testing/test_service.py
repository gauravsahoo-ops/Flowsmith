"""Phase 14 — test-spec evaluation (assertions -> PASS/FAIL/DIFF).

Pure unit tests over app.testing.service.evaluate_test: every assertion
type, regression DIFF detection, path resolution and the report shape.
"""

from __future__ import annotations

from app.testing.service import (
    DIFF,
    FAIL,
    PASS,
    deep_diff,
    evaluate_test,
    normalize_test_data,
)


def _run(**overrides):
    base = {
        "status": "success",
        "error": None,
        "node_statuses": {"t": "success", "fetch": "success", "boom": "error"},
        "node_errors": {"boom": {"code": "HTTP_REQUEST_FAILED", "message": "x"}},
        "results": {"outputs": {
            "t": {"main": [{"hello": "world"}]},
            "fetch": {"main": [{"name": "Ada"}, {"name": "Grace"}]},
        }},
    }
    base.update(overrides)
    return base


def _result(checks):
    return [c["result"] for c in checks]


# ----------------------------------------------------------------------
# workflow-level assertions
# ----------------------------------------------------------------------

def test_workflow_succeeded_passes_and_fails():
    ok = evaluate_test({"assertions": [{"type": "workflow_succeeded"}]}, _run())
    assert ok["verdict"] == PASS and ok["pass"] is True

    bad = evaluate_test({"assertions": [{"type": "workflow_succeeded"}]},
                        _run(status="failed"))
    assert bad["verdict"] == FAIL and bad["pass"] is False


def test_workflow_failed_assertion():
    rep = evaluate_test({"assertions": [{"type": "workflow_failed"}]}, _run(status="failed"))
    assert _result(rep["checks"]) == [PASS]


# ----------------------------------------------------------------------
# node status + error code
# ----------------------------------------------------------------------

def test_node_status_success_error_and_explicit_skip():
    run = _run()
    run["node_statuses"]["later"] = "skipped"  # engine marks downstream skips
    rep = evaluate_test({"assertions": [
        {"type": "node_status", "node_id": "fetch", "expected": "success"},
        {"type": "node_status", "node_id": "boom", "expected": "error"},
        {"type": "node_status", "node_id": "later", "expected": "skipped"},
    ]}, run)
    assert _result(rep["checks"]) == [PASS, PASS, PASS]


def test_node_status_never_run_is_not_skipped():
    rep = evaluate_test(
        {"assertions": [{"type": "node_status", "node_id": "ghost", "expected": "skipped"}]},
        _run(),
    )
    check = rep["checks"][0]
    assert check["result"] == FAIL
    assert check["actual"] == "not_run"


def test_error_code_assertion_pins_typed_error():
    rep = evaluate_test(
        {"assertions": [{"type": "error_code", "node_id": "boom", "code": "HTTP_REQUEST_FAILED"}]},
        _run(),
    )
    assert _result(rep["checks"]) == [PASS]


def test_error_code_assertion_fails_when_no_error():
    rep = evaluate_test(
        {"assertions": [{"type": "error_code", "node_id": "fetch", "code": "HTTP_REQUEST_FAILED"}]},
        _run(),
    )
    check = rep["checks"][0]
    assert check["result"] == FAIL and "(no error)" in check["message"]


# ----------------------------------------------------------------------
# output assertions + path resolution
# ----------------------------------------------------------------------

def test_output_equals_with_dotted_list_path():
    rep = evaluate_test(
        {"assertions": [{"type": "output_equals", "node_id": "fetch",
                         "path": "1.name", "expected": "Grace"}]},
        _run(),
    )
    assert _result(rep["checks"]) == [PASS]


def test_output_equals_mismatch_reports_diff_and_fail():
    rep = evaluate_test(
        {"assertions": [{"type": "output_equals", "node_id": "fetch",
                         "path": "0.name", "expected": "Lovelace"}]},
        _run(),
    )
    check = rep["checks"][0]
    assert check["result"] == FAIL
    assert check["diff"], "mismatch should carry a structural diff"


def test_output_contains_nested_value():
    rep = evaluate_test(
        {"assertions": [{"type": "output_contains", "node_id": "t", "value": "wor"}]},
        _run(),
    )
    assert _result(rep["checks"]) == [PASS]


def test_output_matches_regex():
    rep = evaluate_test(
        {"assertions": [{"type": "output_matches", "node_id": "t",
                         "path": "0.hello", "pattern": "^w.*d$"}]},
        _run(),
    )
    assert _result(rep["checks"]) == [PASS]


def test_output_length_counts_items():
    rep = evaluate_test(
        {"assertions": [{"type": "output_length", "node_id": "fetch", "expected": 2}]},
        _run(),
    )
    assert _result(rep["checks"]) == [PASS]


def test_missing_node_output_fails_cleanly():
    rep = evaluate_test(
        {"assertions": [{"type": "output_equals", "node_id": "nope", "expected": 1}]},
        _run(),
    )
    check = rep["checks"][0]
    assert check["result"] == FAIL
    assert "produced no output" in check["message"]


def test_out_of_range_path_index_fails_cleanly():
    rep = evaluate_test(
        {"assertions": [{"type": "output_equals", "node_id": "fetch",
                         "path": "9.name", "expected": "x"}]},
        _run(),
    )
    assert rep["checks"][0]["result"] == FAIL


# ----------------------------------------------------------------------
# regression snapshots (DIFF)
# ----------------------------------------------------------------------

def test_regression_snapshot_match_passes():
    outputs = _run()["results"]["outputs"]
    rep = evaluate_test({"expected_outputs": {"fetch": outputs["fetch"]}}, _run())
    assert rep["pass"] is True
    assert _result(rep["checks"]) == [PASS]


def test_regression_snapshot_drift_reports_diff_not_plain_fail():
    outputs = _run()["results"]["outputs"]
    drifted = {"main": [{"name": "Ada"}, {"name": "Hopper"}]}
    rep = evaluate_test({"expected_outputs": {"fetch": outputs["fetch"]}},
                        _run(results={"outputs": {"fetch": drifted}}))
    check = rep["checks"][0]
    assert check["result"] == DIFF
    assert rep["pass"] is False
    assert any(d["op"] == "change" and d["path"].endswith("1.name") for d in check["diff"])


def test_regression_snapshot_detects_added_removed_keys_and_lengths():
    expected = {"main": [{"a": 1, "b": 2}]}
    actual = {"main": [{"a": 1, "c": 3}, {"extra": True}]}
    rep = evaluate_test({"expected_outputs": {"n": expected}},
                        _run(results={"outputs": {"n": actual}}))
    ops = {d["op"] for d in rep["checks"][0]["diff"]}
    assert {"missing", "extra", "length"} <= ops


def test_regression_snapshot_for_absent_node_marks_diff():
    rep = evaluate_test({"expected_outputs": {"vanished": {"main": []}}}, _run())
    check = rep["checks"][0]
    assert check["result"] == DIFF


# ----------------------------------------------------------------------
# report shape / mixed verdicts
# ----------------------------------------------------------------------

def test_summary_counts_and_empty_spec_has_no_checks():
    rep = evaluate_test({}, _run())
    assert rep["verdict"] == FAIL  # nothing asserted -> cannot claim PASS
    assert rep["summary"].startswith("no assertions")


def test_one_failed_check_fails_whole_report():
    spec = {"assertions": [
        {"type": "workflow_succeeded"},
        {"type": "output_length", "node_id": "fetch", "expected": 99},
    ]}
    rep = evaluate_test(spec, _run())
    assert rep["pass"] is False
    assert rep["summary"] == "1/2 checks passed"


def test_unknown_assertion_type_surfaces_as_fail_not_crash():
    rep = evaluate_test({"assertions": [{"type": "teleport", "node_id": "t"}]}, _run())
    check = rep["checks"][0]
    assert check["result"] == FAIL
    assert "unknown assertion type" in check["message"]


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def test_normalize_test_data_shapes():
    assert normalize_test_data(None) == [{}]
    assert normalize_test_data({"a": 1}) == [{"a": 1}]
    assert normalize_test_data([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]
    assert normalize_test_data("raw") == [{"value": "raw"}]


def test_deep_diff_bounds_entries():
    big_expected = {"k%d" % i: i for i in range(100)}
    big_actual = {"k%d" % i: i + 1 for i in range(100)}
    diff = deep_diff(big_expected, big_actual)
    assert len(diff) <= 40


def test_deep_diff_numeric_int_float_equivalence():
    diff = deep_diff({"n": 1}, {"n": 1.0})
    assert diff == []
