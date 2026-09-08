"""Phase 15 — candidate validation (the anti-invention gate).

Pure tests over app.ai.validation.validate_candidate / lint_expressions:
each rule fires on exactly its violation, valid candidates pass clean,
and the report is deterministic.
"""

from __future__ import annotations

import pytest

from app.ai.validation import catalog_summary, validate_candidate


@pytest.fixture(scope="module", autouse=True)
def _connectors():
    from app.connectors import get_registry, register_builtin_connectors

    registry = get_registry()
    if not registry.is_initialized():
        registry.initialize()
    register_builtin_connectors()


def _wf(nodes, connections):
    return {"name": "cand", "nodes": nodes, "connections": connections, "settings": {}}


def _valid_candidate():
    return _wf(
        [
            {"id": "start", "type": "manual_trigger", "parameters": {}},
            {"id": "enrich", "type": "set_data",
             "parameters": {"fields": {"greeting": "{{ $json.name | upper }}"}}},
        ],
        [{"source": "start", "target": "enrich"}],
    )


CODES = lambda report: {e["code"] for e in report["errors"]}  # noqa: E731


# ----------------------------------------------------------------------
# happy path
# ----------------------------------------------------------------------

def test_valid_candidate_passes_with_no_issues():
    report = validate_candidate(_valid_candidate(), available_credentials=set())
    assert report["ok"] is True
    assert report["errors"] == [] and report["warnings"] == []


def test_report_is_deterministic():
    cand = _valid_candidate()
    assert validate_candidate(cand, available_credentials=set()) == \
        validate_candidate(cand, available_credentials=set())


# ----------------------------------------------------------------------
# node existence
# ----------------------------------------------------------------------

def test_hallucinated_node_type_rejected():
    cand = _valid_candidate()
    cand["nodes"].append({"id": "x", "type": "quantum_teleport",
                          "parameters": {}, })
    cand["connections"].append({"source": "enrich", "target": "x"})
    report = validate_candidate(cand, available_credentials=set())
    assert "UNKNOWN_NODE_TYPE" in CODES(report)
    assert any(e["node_id"] == "x" for e in report["errors"])


# ----------------------------------------------------------------------
# operation existence + required fields (connector nodes)
# ----------------------------------------------------------------------

def _sf_node(operation="create", **extra):
    params = {"operation": operation, "object_name": "Lead", "record": {"Name": "A"}}
    params.update(extra)
    return {"id": "sf", "type": "salesforce", "parameters": params}


def test_connector_node_with_valid_op_and_fields_passes():
    cand = _wf([{"id": "t", "type": "manual_trigger", "parameters": {}}, _sf_node()],
               [{"source": "t", "target": "sf"}])
    report = validate_candidate(cand, available_credentials={"salesforce"})
    assert report["ok"] is True, report["errors"]


def test_hallucinated_operation_rejected():
    node = _sf_node(operation="transmogrify")
    cand = _wf([{"id": "t", "type": "manual_trigger", "parameters": {}}, node],
               [{"source": "t", "target": "sf"}])
    report = validate_candidate(cand, available_credentials={"salesforce"})
    assert "INVALID_OPERATION" in CODES(report)
    assert "transmogrify" in next(e["message"] for e in report["errors"]
                                  if e["code"] == "INVALID_OPERATION")


def test_missing_required_field_rejected():
    node = _sf_node(record=None)  # create without record fields
    cand = _wf([{"id": "t", "type": "manual_trigger", "parameters": {}}, node],
               [{"source": "t", "target": "sf"}])
    report = validate_candidate(cand, available_credentials={"salesforce"})
    assert "MISSING_REQUIRED_FIELD" in CODES(report)


def test_missing_operation_key_rejected():
    node = _sf_node()
    node["parameters"].pop("operation")
    cand = _wf([{"id": "t", "type": "manual_trigger", "parameters": {}}, node],
               [{"source": "t", "target": "sf"}])
    assert "INVALID_OPERATION" in CODES(validate_candidate(cand, available_credentials=set()))


# ----------------------------------------------------------------------
# schema compatibility + connections
# ----------------------------------------------------------------------

def test_parameter_schema_violation_rejected():
    cand = _valid_candidate()
    # http_request requires url and only allows listed methods.
    cand["nodes"][1] = {"id": "h", "type": "http_request",
                        "parameters": {"method": "TELEPORT", "url": ""}}
    cand["connections"] = [{"source": "start", "target": "h"}]
    report = validate_candidate(cand, available_credentials=set())
    assert "INVALID_PARAMETER" in CODES(report)


def test_cycle_tolerated():
    """Cycles are now allowed in the graph topology. The AI validator
    must not flag them as errors — the engine handles them at runtime."""
    cand = _wf(
        [
            {"id": "a", "type": "set_data", "parameters": {"fields": {}}},
            {"id": "b", "type": "set_data", "parameters": {"fields": {}}},
        ],
        [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    )
    report = validate_candidate(cand, available_credentials=set())
    assert "CYCLIC_GRAPH" not in CODES(report)


def test_connection_to_missing_node_rejected():
    cand = _valid_candidate()
    cand["connections"].append({"source": "enrich", "target": "ghost"})
    assert "INVALID_CONNECTION" in CODES(validate_candidate(cand, available_credentials=set()))


def test_invalid_output_handle_rejected():
    cand = _wf(
        [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "s", "type": "set_data", "parameters": {"fields": {}}},
        ],
        [{"source": "t", "sourceHandle": "false", "target": "s"}],
    )
    assert "INVALID_OUTPUT_HANDLE" in CODES(validate_candidate(cand, available_credentials=set()))


# ----------------------------------------------------------------------
# expressions
# ----------------------------------------------------------------------

def test_unknown_expression_root_rejected():
    cand = _valid_candidate()
    cand["nodes"][1]["parameters"]["fields"]["greeting"] = "{{ window.location }}"
    assert "INVALID_EXPRESSION" in CODES(validate_candidate(cand, available_credentials=set()))


def test_unknown_pipe_rejected():
    cand = _valid_candidate()
    cand["nodes"][1]["parameters"]["fields"]["greeting"] = "{{ $json.name | base64encode }}"
    assert "INVALID_EXPRESSION" in CODES(validate_candidate(cand, available_credentials=set()))


def test_dunder_access_rejected_as_unsafe():
    cand = _valid_candidate()
    cand["nodes"][1]["parameters"]["fields"]["greeting"] = '{{ $json.__class__ }}'
    assert "UNSAFE_EXPRESSION" in CODES(validate_candidate(cand, available_credentials=set()))


def test_unbalanced_braces_rejected():
    cand = _valid_candidate()
    cand["nodes"][1]["parameters"]["fields"]["greeting"] = "{{ $json.name"
    assert "INVALID_EXPRESSION" in CODES(validate_candidate(cand, available_credentials=set()))


def test_known_pipes_and_roots_accepted():
    cand = _valid_candidate()
    cand["nodes"][1]["parameters"]["fields"].update({
        "a": "{{ $json.x | trim }}",
        "b": "{{ $node.start.json.y | int }}",
        "c": "{{ $env.REGION | lower }}",
        "d": "{{ $json.a > 3 ? 'big' : 'small' }}",
    })
    assert validate_candidate(cand, available_credentials=set())["ok"] is True


# ----------------------------------------------------------------------
# credentials (warnings, not errors)
# ----------------------------------------------------------------------

def test_missing_credential_warns_but_does_not_block():
    cand = _wf([{"id": "t", "type": "manual_trigger", "parameters": {}}, _sf_node()],
               [{"source": "t", "target": "sf"}])
    report = validate_candidate(cand, available_credentials=set())
    assert report["ok"] is True  # warnings never block creation
    assert any(w["code"] == "MISSING_CREDENTIAL" and w["node_id"] == "sf"
               for w in report["warnings"])
    assert any("'salesforce'" in w["message"] for w in report["warnings"])


def test_connected_credential_no_warning():
    cand = _wf([{"id": "t", "type": "manual_trigger", "parameters": {}}, _sf_node()],
               [{"source": "t", "target": "sf"}])
    report = validate_candidate(cand, available_credentials={"salesforce"})
    assert report["warnings"] == []


# ----------------------------------------------------------------------
# catalog summary sanity
# ----------------------------------------------------------------------

def test_catalog_summary_counts_real_surface():
    counts = catalog_summary()
    assert counts["nodes"] >= 20
    assert counts["connectors"] >= 15
    assert counts["operations"] >= counts["connectors"]
