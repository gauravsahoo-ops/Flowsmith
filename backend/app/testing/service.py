"""Workflow test evaluation (Phase 14: first-class workflow testing).

Pure evaluation layer between a finished execution and its saved test
spec. A WorkflowTest carries four sections:

- ``test_data``        trigger items fed to the run
- ``mocks``            HTTP mock rules (see app/security/http_mocks.py);
                       matched outbound calls are answered locally,
                       unmatched ones are BLOCKED so a test can never
                       mutate production systems
- ``assertions``       per-run/per-node checks
- ``expected_outputs`` regression snapshot compared node-by-node

``evaluate_test(spec, run)`` turns those into a report::

    {"pass": bool, "verdict": "PASS"|"FAIL", "summary": "3/4 checks passed",
     "checks": [{"name", "target", "type", "result": "PASS"|"FAIL"|"DIFF",
                 "message", "expected", "actual", "diff"}]}

Result vocabulary:
- ``PASS`` — the check held.
- ``FAIL`` — an explicit assertion did not hold (or errored).
- ``DIFF`` — regression mismatch against ``expected_outputs``; same
  failure semantics as FAIL but rendered as a structural diff so users
  can see exactly what drifted.

No I/O, no imports from the app beyond nothing at all: this module is
deliberately dependency-free so it can be unit-tested exhaustively.
"""

from __future__ import annotations

import re
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
DIFF = "DIFF"

# Assertion types understood by evaluate_test(). Unknown types do not
# crash a run; they surface as FAIL with a helpful message.
ASSERTION_TYPES = (
    "workflow_succeeded",
    "workflow_failed",
    "node_status",
    "output_equals",
    "output_contains",
    "output_matches",
    "output_length",
    "error_code",
)

MAX_DIFF_ENTRIES = 40


def normalize_test_data(raw: Any) -> list[dict[str, Any]]:
    """Trigger items for a test run, accepting the three authoring shapes:

    - ``None``          -> [{}] (one empty item, like manual runs)
    - ``{...}``         -> [obj] (single item)
    - ``[...]``         -> as-is (each entry should be an object)
    """
    if raw is None:
        return [{}]
    if isinstance(raw, list):
        return [item if isinstance(item, dict) else {"value": item} for item in raw]
    if isinstance(raw, dict):
        return [raw]
    return [{"value": raw}]


def _check(
    *,
    name: str,
    target: str,
    type: str,
    result: str,
    message: str,
    expected: Any = None,
    actual: Any = None,
    diff: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "target": target,
        "type": type,
        "result": result,
        "message": message,
        "expected": expected,
        "actual": actual,
        "diff": diff or None,
    }


def _resolve_path(value: Any, path: str) -> tuple[Any, str | None]:
    """Walk a dotted path ('0.user.name') through lists/dicts.

    Returns (resolved, error); error is None on success. Integer-looking
    segments index lists; anything else keys dicts.
    """
    if path in ("", None):
        return value, None
    cur = value
    for part in str(path).split("."):
        if isinstance(cur, list):
            try:
                idx = int(part)
            except ValueError:
                return None, f"path segment '{part}' expects an object, found a list"
            if idx < 0 or idx >= len(cur):
                return None, f"path index {idx} out of range (list has {len(cur)} items)"
            cur = cur[idx]
        elif isinstance(cur, dict):
            if part not in cur:
                return None, f"path key '{part}' missing"
            cur = cur[part]
        else:
            return None, f"path segment '{part}' cannot resolve inside {type(cur).__name__}"
    return cur, None


def _json_safe(value: Any) -> Any:
    """Coerce values to JSON-friendly shapes for the report payload."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return repr(value)


def deep_diff(expected: Any, actual: Any, path: str = "") -> list[dict[str, Any]]:
    """Structural diff used by regression (snapshot) checks.

    Entries: {op: change|add|remove|type, path, expected?, actual?}.
    Bounded so a wildly different snapshot can't flood the report.
    """
    out: list[dict[str, Any]] = []

    def walk(exp: Any, act: Any, p: str) -> None:
        if len(out) >= MAX_DIFF_ENTRIES:
            return
        numeric = isinstance(exp, (int, float)) and isinstance(act, (int, float))
        if type(exp) is not type(act) and not numeric and not (
            isinstance(exp, (dict, list)) and isinstance(act, (dict, list))
        ):
            out.append({"op": "type", "path": p or "$", "expected": _json_safe(exp), "actual": _json_safe(act)})
            return
        if isinstance(exp, dict) and isinstance(act, dict):
            for key in exp.keys() | act.keys():
                if len(out) >= MAX_DIFF_ENTRIES:
                    return
                kp = f"{p}.{key}" if p else str(key)
                if key not in act:
                    out.append({"op": "missing", "path": kp, "expected": _json_safe(exp[key])})
                elif key not in exp:
                    out.append({"op": "extra", "path": kp, "actual": _json_safe(act[key])})
                else:
                    walk(exp[key], act[key], kp)
        elif isinstance(exp, list) and isinstance(act, list):
            if len(exp) != len(act):
                out.append({
                    "op": "length", "path": p or "$",
                    "expected": len(exp), "actual": len(act),
                })
            for i in range(min(len(exp), len(act))):
                if len(out) >= MAX_DIFF_ENTRIES:
                    return
                walk(exp[i], act[i], f"{p}.{i}" if p else str(i))
        elif exp != act:
            out.append({"op": "change", "path": p or "$", "expected": _json_safe(exp), "actual": _json_safe(act)})

    walk(expected, actual, path)
    return out[:MAX_DIFF_ENTRIES]


def _node_outputs(outputs: dict[str, Any], node_id: str) -> tuple[list[dict[str, Any]], str | None]:
    """Main-handle items for one node from the persisted results envelope."""
    if not isinstance(outputs, dict) or node_id not in outputs:
        return [], f"node '{node_id}' produced no output (did it run?)"
    by_handle = outputs[node_id]
    if isinstance(by_handle, dict):
        items = by_handle.get("main", [])
    else:  # defensive: raw list stored under the node id
        items = by_handle
    if not isinstance(items, list):
        return [], f"node '{node_id}' output is not a list"
    return items, None


def _evaluate_assertion(a: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """One configured assertion -> one check dict."""
    kind = str(a.get("type") or "").strip()
    node_id = str(a.get("node_id") or "")
    statuses: dict[str, str] = run.get("node_statuses") or {}
    outputs = (run.get("results") or {}).get("outputs") or {}

    if kind == "workflow_succeeded":
        ok = run.get("status") == "success"
        return _check(
            name="workflow succeeded", target="workflow", type=kind,
            result=PASS if ok else FAIL,
            message="run completed successfully" if ok else f"run status was '{run.get('status')}'",
            expected="success", actual=run.get("status"),
        )

    if kind == "workflow_failed":
        ok = run.get("status") == "failed"
        return _check(
            name="workflow failed", target="workflow", type=kind,
            result=PASS if ok else FAIL,
            message="run failed as expected" if ok else f"run status was '{run.get('status')}'",
            expected="failed", actual=run.get("status"),
        )

    if kind == "node_status":
        if not node_id:
            return _check(name="node status", target="-", type=kind, result=FAIL,
                          message="assertion is missing 'node_id'")
        expected = str(a.get("expected") or "success")
        actual = statuses.get(node_id, "not_run")
        ok = actual == expected
        return _check(
            name=f"node '{node_id}' status", target=node_id, type=kind,
            result=PASS if ok else FAIL,
            message=f"expected {expected}, got {actual}",
            expected=expected, actual=actual,
        )

    if kind in ("output_equals", "output_contains", "output_matches", "output_length"):
        label = {
            "output_equals": "equals", "output_contains": "contains",
            "output_matches": "matches", "output_length": "length",
        }[kind]
        if not node_id:
            return _check(name=f"output {label}", target="-", type=kind, result=FAIL,
                          message="assertion is missing 'node_id'")
        items, err = _node_outputs(outputs, node_id)
        if err:
            return _check(name=f"output {label}", target=node_id, type=kind,
                          result=FAIL, message=err)
        scope: Any = items
        path = str(a.get("path") or "")
        if path:
            scope, perr = _resolve_path(items, path)
            if perr:
                return _check(name=f"output {label}", target=node_id, type=kind,
                              result=FAIL, message=perr, expected=a.get("expected", a.get("value", a.get("pattern"))))

        if kind == "output_equals":
            expected = a.get("expected")
            ok = scope == expected
            return _check(
                name=f"output {label}{_path_suffix(path)}", target=node_id, type=kind,
                result=PASS if ok else FAIL,
                message="values are equal" if ok else "value differs",
                expected=_json_safe(expected), actual=_json_safe(scope),
                diff=None if ok else deep_diff(expected, scope),
            )
        if kind == "output_contains":
            needle = a.get("value")
            try:
                ok = _contains(scope, needle)
            except TypeError:
                ok = False
            return _check(
                name=f"output {label}{_path_suffix(path)}", target=node_id, type=kind,
                result=PASS if ok else FAIL,
                message="value found" if ok else "value not found",
                expected=_json_safe(needle), actual=_json_safe(scope),
            )
        if kind == "output_matches":
            pattern = str(a.get("pattern") or "")
            try:
                ok = bool(pattern) and re.search(pattern, str(scope)) is not None
            except re.error as exc:
                return _check(name=f"output matches{_path_suffix(path)}", target=node_id,
                              type=kind, result=FAIL, message=f"invalid regex: {exc}")
            return _check(
                name=f"output matches{_path_suffix(path)}", target=node_id, type=kind,
                result=PASS if ok else FAIL,
                message="pattern matched" if ok else f"pattern '{pattern}' did not match",
                expected=pattern, actual=_json_safe(scope),
            )
        # output_length
        if not isinstance(scope, (list, dict, str)):
            return _check(name="output length", target=node_id, type=kind,
                          result=FAIL, message="resolved value has no length")
        length = len(scope)
        expected = a.get("expected")
        try:
            ok = length == int(expected)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return _check(name="output length", target=node_id, type=kind,
                          result=FAIL, message="'expected' must be an integer")
        return _check(
            name=f"output length{_path_suffix(path)}", target=node_id, type=kind,
            result=PASS if ok else FAIL,
            message=f"expected {expected} items, found {length}",
            expected=expected, actual=length,
        )

    if kind == "error_code":
        if not node_id:
            return _check(name="error code", target="-", type=kind, result=FAIL,
                          message="assertion is missing 'node_id'")
        expected = str(a.get("code") or "")
        # Node errors surface through the run's trace/statuses; the run
        # envelope carries only the workflow-level error, so accept both
        # explicit per-node error maps and the workflow error.
        node_error = ((run.get("node_errors") or {}).get(node_id)) or {}
        code = str(node_error.get("code") or "")
        wf_error = run.get("error") or {}
        if not code and statuses.get(node_id) in ("error", "failed"):
            code = str(wf_error.get("code") or "NODE_ERROR")
        ok = code != "" and code == expected
        return _check(
            name=f"node '{node_id}' error code", target=node_id, type=kind,
            result=PASS if ok else FAIL,
            message=f"expected error code {expected}, got {code or '(no error)'}",
            expected=expected, actual=code or None,
        )

    return _check(
        name=str(a.get("name") or kind or "assertion"), target=node_id or "-",
        type=kind or "(none)", result=FAIL,
        message=f"unknown assertion type '{kind}'. Known: {', '.join(ASSERTION_TYPES)}",
    )


def _path_suffix(path: str) -> str:
    return f" at '{path}'" if path else ""


def _contains(scope: Any, needle: Any) -> bool:
    if isinstance(scope, str):
        return str(needle) in scope
    if isinstance(scope, list):
        return any(_contains(item, needle) for item in scope)
    if isinstance(scope, dict):
        if isinstance(needle, dict):
            return all(key in scope and _contains(scope[key], val) for key, val in needle.items())
        return any(_contains(v, needle) for v in scope.values())
    return scope == needle


def _regression_checks(expected_outputs: Any, run: dict[str, Any]) -> list[dict[str, Any]]:
    """Snapshot comparison: expected vs actual per node -> PASS/DIFF."""
    outputs = (run.get("results") or {}).get("outputs") or {}
    checks: list[dict[str, Any]] = []
    if not isinstance(expected_outputs, dict):
        return [_check(
            name="regression snapshot", target="workflow", type="regression",
            result=FAIL, message="'expected_outputs' must be an object of node_id -> outputs",
        )]
    for node_id, expected in sorted(expected_outputs.items()):
        actual = outputs.get(node_id)
        if actual is None:
            diff = [{"op": "missing", "path": node_id, "expected": _json_safe(expected)}]
            checks.append(_check(
                name=f"regression: node '{node_id}'", target=node_id, type="regression",
                result=DIFF,
                message="node produced no output but the snapshot expects one",
                expected=_json_safe(expected), actual=None, diff=diff,
            ))
            continue
        diff = deep_diff(expected, actual)
        checks.append(_check(
            name=f"regression: node '{node_id}'", target=node_id, type="regression",
            result=PASS if not diff else DIFF,
            message="outputs match the snapshot" if not diff
            else f"{len(diff)} difference(s) vs snapshot",
            expected=_json_safe(expected), actual=_json_safe(actual),
            diff=diff or None,
        ))
    return checks


def evaluate_test(test_spec: dict[str, Any] | None, run: dict[str, Any]) -> dict[str, Any]:
    """Build the PASS/FAIL/DIFF report for one finished test-mode run.

    ``run`` is the runtime's view of the finished execution:
    ``{status, error, node_statuses, results: {outputs}, node_errors?}``.
    """
    spec = test_spec or {}
    checks: list[dict[str, Any]] = []

    assertions = spec.get("assertions") or []
    if isinstance(assertions, dict):  # tolerate a single object form
        assertions = [assertions]
    for a in assertions:
        if isinstance(a, dict):
            checks.append(_evaluate_assertion(a, run))

    expected_outputs = spec.get("expected_outputs")
    if expected_outputs:
        checks.extend(_regression_checks(expected_outputs, run))

    passed = sum(1 for c in checks if c["result"] == PASS)
    total = len(checks)
    all_pass = total > 0 and passed == total
    return {
        "pass": all_pass,
        "verdict": PASS if all_pass else FAIL,
        "summary": f"{passed}/{total} checks passed" if total else "no assertions configured",
        "execution_status": run.get("status"),
        "checks": checks,
    }
