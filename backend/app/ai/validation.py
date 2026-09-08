"""Candidate validation (Phase 15): the AI may only reference what exists.

Every generated workflow passes through :func:`validate_candidate`
before it is ever shown to a user. Checks, in order:

1. **Node existence** — engine graph validation (unknown types fail,
   including connector-only node types).
2. **Schema compatibility** — parameters validated against each node's
   real pydantic schema; connector operations against the definition's
   input schema (required fields).
3. **Operation existence** — ``parameters.operation`` must be one of
   the connector definition's registered operations.
4. **Connections** — references resolve, handles exist, graph acyclic.
5. **Expressions** — every ``{{ ... }}`` block must parse: known roots,
   no dunder access, known pipes, balanced braces/parens.
6. **Credentials** (warning-level) — nodes referencing a credential type
   the user has not connected are flagged so the preview can say so;
   creation stays possible because credentials can be added later.

Output: {"ok": bool, "errors": [issue], "warnings": [issue]} where an
issue is {code, node_id, field, message}. Pure and deterministic.
"""

from __future__ import annotations

import re
from typing import Any

from app.ai.catalog import build_connector_entries
from app.engine.errors import WorkflowValidationError
from app.engine.expressions import _EXPR_RE
from app.engine.graph import build_graph, topological_sort, validate_graph
from app.schemas.workflow import Workflow

# Pipes implemented by app/engine/expressions.py::_apply_pipe.
KNOWN_PIPES = frozenset(
    {"typeof", "int", "float", "bool", "upper", "lower", "trim", "length", "contains", "replace"}
)
KNOWN_ROOTS = frozenset({"$json", "$node", "$cred", "$env", "$workflow", "$execution", "$now"})
_DUNDER_RE = re.compile(r"__[\w]+__")

_ISSUE_CODES = (
    "UNKNOWN_NODE_TYPE",
    "INVALID_PARAMETER",
    "INVALID_SETTING",
    "DUPLICATE_NODE_ID",
    "EMPTY_WORKFLOW",
    "INVALID_CONNECTION",
    "INVALID_INPUT_HANDLE",
    "INVALID_OUTPUT_HANDLE",
    "CYCLIC_GRAPH",
    "INVALID_OPERATION",
    "MISSING_REQUIRED_FIELD",
    "INVALID_EXPRESSION",
    "UNSAFE_EXPRESSION",
    "MISSING_CREDENTIAL",
)


def _issue(code: str, *, node_id: str | None = None, field: str | None = None, message: str) -> dict:
    if code not in _ISSUE_CODES:
        raise ValueError(f"Unknown issue code '{code}'")  # keeps the vocabulary closed
    return {"code": code, "node_id": node_id, "field": field, "message": message}


def check_connector_operation(definition: Any, parameters: dict[str, Any]) -> list[dict]:
    """Operation existence + required-field checks against one definition."""
    issues: list[dict] = []
    ops = (getattr(definition, "operations", None) or {})
    op_name = str((parameters or {}).get("operation") or "")
    if not ops:
        return issues
    if not op_name:
        issues.append(_issue(
            "INVALID_OPERATION", field="parameters.operation",
            message=f"Connector node requires 'operation' "
                    f"(one of: {', '.join(sorted(ops))}).",
        ))
        return issues
    if op_name not in ops:
        issues.append(_issue(
            "INVALID_OPERATION", field="parameters.operation",
            message=f"Operation '{op_name}' does not exist on connector "
                    f"'{definition.connector_key}' (one of: {', '.join(sorted(ops))}).",
        ))
        return issues
    schema = ops[op_name].input_schema or {}
    for required in schema.get("required") or []:
        value = (parameters or {}).get(required)
        if value in (None, "", [], {}):
            issues.append(_issue(
                "MISSING_REQUIRED_FIELD", field=f"parameters.{required}",
                message=f"Operation '{op_name}' requires '{required}'.",
            ))
    return issues


def validate_node_parameters(node_type: str, parameters: dict[str, Any]) -> list[dict]:
    """Validate ONE node's parameters against reality (Phase 16 reuse).

    Built-in node classes win over connector fallbacks (executor rule);
    returns [] when everything checks out.
    """
    from app.nodes.registry import NODE_REGISTRY

    cls = NODE_REGISTRY.get(node_type)
    if cls is not None:
        issues: list[dict] = []
        try:
            cls().build_params(parameters or {})
        except Exception as exc:
            issues.append(_issue("INVALID_PARAMETER", field="parameters", message=str(exc)))
        return issues
    definition = _connector_definition_for(node_type)
    if definition is None:
        return [_issue("UNKNOWN_NODE_TYPE", message=f"Unknown node type '{node_type}'.")]
    return check_connector_operation(definition, parameters)


def _connector_definition_for(node_type: str) -> Any:
    """The connector definition serving a CONNECTOR-ONLY node type.

    Mirrors the executor's routing rule: a registered node class always
    wins over the connector fallback, so built-ins are never op-checked
    here (their pydantic schema already covers parameters). Definitions
    without operations (trigger-only connectors like `webhook`) are not
    operation surfaces either.
    """
    from app.connectors import ensure_builtin_connectors, get_registry as get_connector_registry
    from app.nodes.registry import NODE_REGISTRY

    if NODE_REGISTRY.get(node_type) is not None:
        return None
    ensure_builtin_connectors()
    registry = get_connector_registry()
    connector = registry.primary_for_node_type(node_type)
    if connector is None:
        return None
    try:
        definition = registry.get_definition(connector.connector_id)
    except Exception:
        return None
    if definition is not None and not definition.operations:
        return None
    return definition


def lint_expressions(value: Any, *, node_id: str = "", path: str = "") -> list[dict]:
    """Syntax-lint every {{ }} block in a parameter tree (no evaluation)."""
    issues: list[dict] = []
    if isinstance(value, dict):
        for key, sub in value.items():
            issues.extend(lint_expressions(sub, node_id=node_id, path=f"{path}.{key}" if path else str(key)))
        return issues
    if isinstance(value, list):
        for i, item in enumerate(value):
            issues.extend(lint_expressions(item, node_id=node_id, path=f"{path}.{i}" if path else str(i)))
        return issues
    if not isinstance(value, str):
        return issues

    # Unbalanced braces: count {{ vs }} occurrences.
    opens = value.count("{{")
    closes = value.count("}}")
    if opens != closes or "{{{" in value or "}}}" in value:
        issues.append(_issue(
            "INVALID_EXPRESSION", node_id=node_id, field=path,
            message=f"Unbalanced expression braces in {value[:60]!r}.",
        ))
        return issues

    for match in _EXPR_RE.finditer(value):
        expr = match.group(1).strip()
        if not expr:
            issues.append(_issue("INVALID_EXPRESSION", node_id=node_id, field=path,
                                 message="Empty {{ }} expression."))
            continue
        if expr.count("(") != expr.count(")"):
            issues.append(_issue("INVALID_EXPRESSION", node_id=node_id, field=path,
                                 message=f"Unbalanced parentheses in {{{{{expr}}}}}."))
            continue
        if _DUNDER_RE.search(expr):
            issues.append(_issue("UNSAFE_EXPRESSION", node_id=node_id, field=path,
                                 message=f"Dunder access is not allowed: {expr!r}."))
            continue
        root = expr.split(".", 1)[0].split("[", 1)[0].split("|", 1)[0].split(" ", 1)[0].strip()
        if root not in KNOWN_ROOTS:
            issues.append(_issue("INVALID_EXPRESSION", node_id=node_id, field=path,
                                 message=f"Unknown root '{root}' (known: {', '.join(sorted(KNOWN_ROOTS))})."))
            continue
        for pipe_match in re.finditer(r"\|\s*(\w+)", expr):
            pipe = pipe_match.group(1)
            if pipe not in KNOWN_PIPES:
                issues.append(_issue(
                    "INVALID_EXPRESSION", node_id=node_id, field=path,
                    message=f"Unknown pipe '|{pipe}' (known: {', '.join(sorted(KNOWN_PIPES))}).",
                ))
    return issues


def validate_candidate(candidate: dict[str, Any], *, available_credentials: set[str]) -> dict[str, Any]:
    """Validate one generated workflow candidate against reality.

    `available_credentials` is the set of credential TYPES the user has
    saved (e.g. {"salesforce", "http"}).
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    workflow = Workflow.model_validate({**candidate, "id": candidate.get("id") or "wf_ai"})

    # 1-4: engine validation with FULL parameter checks + acyclicity.
    try:
        validate_graph(workflow, validate_params=True)
        topological_sort(build_graph(workflow))
    except (ValueError, WorkflowValidationError) as exc:
        raw_issues = getattr(exc, "issues", None) or [
            {"code": "INVALID_PARAMETER", "node_id": None, "field": None, "message": str(exc)}
        ]
        for raw in raw_issues:
            code = raw.get("code") or "INVALID_PARAMETER"
            errors.append(_issue(
                code if code in _ISSUE_CODES else "INVALID_PARAMETER",
                node_id=raw.get("node_id"), field=raw.get("field"),
                message=raw.get("message") or str(raw),
            ))

    for node in workflow.nodes:
        # 3+2b: connector operation existence + required fields.
        definition = _connector_definition_for(node.type)
        if definition is not None:
            for issue in check_connector_operation(definition, node.parameters or {}):
                issue["node_id"] = node.id
                errors.append(issue)

        # 5: expressions.
        errors.extend(lint_expressions(node.parameters, node_id=node.id))

        # 6: credentials the user does not have -> warning (not blocking).
        needed = set()
        from app.nodes.registry import NODE_REGISTRY

        cls = NODE_REGISTRY.get(node.type)
        if cls is not None:
            needed.update(cls.credential_types or [])
        if definition is not None:
            for op in (definition.operations or {}).values():
                if getattr(op, "credential_require", None):
                    needed.add(str(op.credential_require))
        referenced = set((node.credentials or {}).keys())
        for cred_type in sorted(needed):
            if cred_type not in available_credentials and cred_type not in referenced:
                warnings.append(_issue(
                    "MISSING_CREDENTIAL", node_id=node.id, field="credentials",
                    message=f"No saved '{cred_type}' credential; connect one before running.",
                ))

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def catalog_summary() -> dict[str, int]:
    """Counts used by tests/metrics: how many building blocks are offered."""
    catalog = build_connector_entries()
    return {
        "nodes": _node_count(),
        "connectors": len(catalog),
        "operations": sum(len(c["operations"]) for c in catalog),
    }


def _node_count() -> int:
    from app.nodes.registry import NODE_REGISTRY

    return len(NODE_REGISTRY)
