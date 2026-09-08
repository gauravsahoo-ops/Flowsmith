"""AI automation assistant (Phase 16).

Six assist surfaces over ONE contract — every suggestion is:

- **validated**   against real schemas / the live expression engine /
                  deterministic analyzers before it reaches the user
- **editable**    plain JSON/text the client may change freely
- **explainable** each suggestion carries a human-readable rationale
- **non-destructive** NOTHING here writes to workflows; applying a
                  suggestion is a normal client-side edit that still
                  goes through the user's explicit save

LLM involvement is optional and injectable (`chat=`), so every surface
has deterministic evaluation tests. Where correctness can be computed
(workflow analysis, documentation skeleton), it IS computed — the model
only adds narrative on top of ground truth, never instead of it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from app.ai.validation import (
    lint_expressions,
    validate_node_parameters,
)
from app.engine import expressions

ChatFn = Callable[..., Awaitable[dict[str, Any]]]


class AssistantError(Exception):
    """The model produced unusable output for an assist surface."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _parse_json(content: str) -> Any:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AssistantError("Model output was not a JSON object.") from None
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            raise AssistantError("Model output was not a JSON object.") from None


async def _complete_json(chat: ChatFn, llm: dict, messages: list[dict], max_tokens: int = 1200) -> Any:
    message = await chat(llm, messages, temperature=0.2, response_json=True, max_tokens=max_tokens)
    return _parse_json(message.get("content") or "")


# ----------------------------------------------------------------------
# 1. Field mapping
# ----------------------------------------------------------------------

async def suggest_field_mapping(
    *,
    target_node_type: str,
    target_fields: list[str],
    source_fields: list[dict[str, Any]],
    intent: str = "",
    chat: ChatFn,
    llm: dict[str, Any],
) -> dict[str, Any]:
    """Map upstream output fields onto a node's input fields.

    `source_fields` are typed leaf paths from the last execution
    (upstream-fields machinery); `target_fields` are the node's input
    paths. Every proposed expression is linted; references to source
    fields that do not exist are flagged as warnings (runtime data may
    legitimately differ from the sample).
    """
    system = (
        "You map data between workflow nodes. Respond with ONLY a JSON object:"
        '{"mapping": {"<target_field>": "{{ $json.<source_path> }}"},'
        ' "explanation": "one short paragraph"}'
        " Use ONLY {{ }} expressions over the listed source fields"
        " (root $json). Never invent fields. If no source field fits a"
        " target, omit it."
    )
    user_payload = {
        "target_node_type": target_node_type,
        "intent": intent,
        "target_fields": target_fields,
        "source_fields": [
            {"path": f.get("path"), "type": f.get("type"), "sample": f.get("sample")}
            for f in source_fields
        ],
    }
    parsed = await _complete_json(chat, llm, [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ])
    raw_mapping = parsed.get("mapping") if isinstance(parsed, dict) else None
    if not isinstance(raw_mapping, dict):
        raise AssistantError("Model did not return a 'mapping' object.")

    known_paths = {str(f.get("path") or "") for f in source_fields}
    mapping: dict[str, str] = {}
    issues: list[dict[str, Any]] = []
    for key, value in raw_mapping.items():
        if not isinstance(value, str):
            continue
        mapping[str(key)] = value
    # Validate every expression.
    for field, expression in mapping.items():
        for issue in lint_expressions({field: expression}):
            issues.append({"severity": "error", **issue})
        for match in re.finditer(r"\$json\.([A-Za-z0-9_\[\]\.]+)", expression):
            ref = match.group(1).rstrip(".")
            if known_paths and not any(p == ref or p.startswith(ref) or ref.startswith(p) for p in known_paths):
                issues.append({
                    "severity": "warning", "code": "UNKNOWN_SOURCE_FIELD",
                    "node_id": None, "field": field,
                    "message": f"'{ref}' was not present in the sampled upstream data.",
                })
    return {
        "mapping": mapping,
        "explanation": str(parsed.get("explanation") or "") if isinstance(parsed, dict) else "",
        "issues": issues,
        "ok": not any(i["severity"] == "error" for i in issues),
    }


# ----------------------------------------------------------------------
# 2. Expression generation
# ----------------------------------------------------------------------

async def suggest_expression(
    *,
    description: str,
    sample_item: dict[str, Any] | None = None,
    chat: ChatFn,
    llm: dict[str, Any],
) -> dict[str, Any]:
    """Turn a natural-language description into one validated {{ }}
    expression, evaluated against the provided sample for preview."""
    system = (
        "You write single expressions for a safe {{ }} template engine."
        ' Respond ONLY: {"expression": "{{ ... }}", "explanation": "..."}'
        " Roots: $json (input item fields), $env.KEY, $now, $workflow.id,"
        " $execution.id, $node.<id>.json.<field>. Pipes: int float bool"
        " typeof upper lower trim length contains(\"x\") replace(\"a\",\"b\")."
        " Comparisons (+ ? : ternary) allowed. No functions, no imports,"
        " no dunder access."
    )
    parsed = await _complete_json(chat, llm, [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps({
            "description": description,
            "sample_item": sample_item or {},
        }, ensure_ascii=False)},
    ], max_tokens=400)
    expression = str(parsed.get("expression") or "") if isinstance(parsed, dict) else ""
    explanation = str(parsed.get("explanation") or "") if isinstance(parsed, dict) else ""
    if not expression:
        raise AssistantError("Model returned no expression.")

    issues = lint_expressions({"expression": expression})
    preview_value = None
    if not issues:
        try:
            preview_value = expressions.resolve(expression, expressions.build_context(
                [sample_item or {}], {}, "wf_preview", "exec_preview", None, {},
            ))
        except Exception:  # preview is best-effort; lint already passed
            preview_value = None
    return {
        "expression": expression,
        "explanation": explanation,
        "preview_value": preview_value,
        "issues": [{"severity": "error", **i} for i in issues],
        "ok": not issues,
    }


# ----------------------------------------------------------------------
# 3. Node configuration
# ----------------------------------------------------------------------

async def suggest_node_config(
    *,
    node_type: str,
    operation: str | None,
    intent: str,
    available_credentials: set[str],
    chat: ChatFn,
    llm: dict[str, Any],
) -> dict[str, Any]:
    """Propose parameters for one node; validated against its real schema."""
    from app.ai.catalog import build_connector_entries, build_node_entries

    ground_truth: dict[str, Any] | None = next(
        (n for n in build_node_entries() if n["type"] == node_type), None)
    connector_entry = None
    if ground_truth is None:
        for entry in build_connector_entries():
            if node_type in entry["node_types"]:
                connector_entry = entry
                break
        ground_truth = connector_entry
    if ground_truth is None:
        raise AssistantError(f"Unknown node type '{node_type}'.")

    system = (
        "You configure workflow nodes using ONLY the schema provided."
        ' Respond ONLY: {"parameters": {...}, "explanation": "..."}'
        " Values may use {{ $json.field }} expressions where data flows in."
        " Never invent parameter names."
    )
    user_payload = {
        "node_type": node_type,
        "operation_hint": operation,
        "intent": intent,
        "schema": ground_truth,
    }
    parsed = await _complete_json(chat, llm, [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ])
    parameters = parsed.get("parameters") if isinstance(parsed, dict) else None
    if operation:
        parameters = {**(parameters or {}), "operation": operation}
    if not isinstance(parameters, dict):
        raise AssistantError("Model did not return a 'parameters' object.")
    if operation:
        parameters["operation"] = operation  # pinned by the caller, not the model

    issues = validate_node_parameters(node_type, parameters)
    return {
        "parameters": parameters,
        "explanation": str(parsed.get("explanation") or "") if isinstance(parsed, dict) else "",
        "issues": [{"severity": "error", **i} for i in issues],
        "ok": not issues,
    }


# ----------------------------------------------------------------------
# 4-6. Deterministic workflow analysis + narrative surfaces
# ----------------------------------------------------------------------

_SIDE_EFFECT_TYPES = {"http_request", "database_query", "graphql"}

def analyze_workflow(workflow_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic optimization findings (no LLM, always correct)."""
    nodes = workflow_data.get("nodes") or []
    connections = workflow_data.get("connections") or []
    findings: list[dict[str, Any]] = []

    reachable = set()
    outgoing: dict[str, list[str]] = {}
    for c in connections:
        outgoing.setdefault(c.get("source"), []).append(c.get("target"))
    for n in nodes:
        if n.get("type") in ("manual_trigger", "webhook", "schedule", "salesforce_trigger"):
            stack, seen = [n.get("id")], set()
            while stack:
                cur = stack.pop()
                if cur in seen or cur is None:
                    continue
                seen.add(cur)
                stack.extend(outgoing.get(cur, []))
            reachable |= seen

    for node in nodes:
        nid = node.get("id")
        ntype = node.get("type")
        settings = node.get("settings") or {}
        params = node.get("parameters") or {}
        if nid not in reachable:
            findings.append({
                "code": "UNREACHABLE_NODE", "node_id": nid, "severity": "warn",
                "message": "Node is not connected to any trigger and will never run.",
            })
        needs_timeout = ntype in _SIDE_EFFECT_TYPES or bool(params.get("operation"))
        if needs_timeout and not settings.get("timeout_seconds"):
            findings.append({
                "code": "NO_TIMEOUT", "node_id": nid, "severity": "info",
                "message": "No per-node timeout; a hung provider stalls the whole run.",
                "fix": {"settings": {"timeout_seconds": 30}},
            })
        if ntype == "http_request" and params.get("method") in ("GET", "PUT", "DELETE") \
                and not settings.get("retry_max_attempts"):
            findings.append({
                "code": "NO_RETRY_ON_IDEMPOTENT", "node_id": nid, "severity": "info",
                "message": "Idempotent request without retries; transient failures fail the run.",
                "fix": {"settings": {"retry_max_attempts": 3, "retry_backoff_seconds": 2}},
            })
    return findings


def _structure_summary(workflow_data: dict[str, Any]) -> dict[str, Any]:
    """Ground-truth graph facts used by explain/document (no LLM)."""
    nodes = workflow_data.get("nodes") or []
    conns = workflow_data.get("connections") or []
    outgoing: dict[str, list[str]] = {}
    for c in conns:
        outgoing.setdefault(c.get("source"), []).append(c.get("target"))
    trigger_types = ("manual_trigger", "webhook", "schedule", "salesforce_trigger")
    triggers = [n for n in nodes if n.get("type") in trigger_types]
    trigger_ids = {n.get("id") for n in triggers}
    return {
        "name": workflow_data.get("name"),
        "triggers": [{"id": n.get("id"), "type": n.get("type")} for n in triggers],
        "steps": [{
            "id": n.get("id"),
            "type": n.get("type"),
            "operation": (n.get("parameters") or {}).get("operation"),
            "feeds": outgoing.get(n.get("id"), []),
        } for n in nodes if n.get("id") not in trigger_ids],
    }


async def suggest_optimizations(
    workflow_data: dict[str, Any], *, chat: ChatFn, llm: dict[str, Any]
) -> dict[str, Any]:
    """Findings are computed deterministically; the model only narrates."""
    findings = analyze_workflow(workflow_data)
    advisory: list[dict[str, str]] = []
    if findings:
        try:
            parsed = await _complete_json(chat, llm, [
                {"role": "system", "content":
                    "You advise on workflow reliability. Respond ONLY:"
                    ' {"suggestions": [{"title": "...", "detail": "..."}]}'
                    " Base every suggestion ONLY on the findings given."},
                {"role": "user", "content": json.dumps(findings, ensure_ascii=False)},
            ], max_tokens=700)
            raw = parsed.get("suggestions") if isinstance(parsed, dict) else None
            if isinstance(raw, list):
                advisory = [s for s in raw if isinstance(s, dict) and s.get("title")]
        except AssistantError:
            pass  # advisory-only: deterministic findings remain the answer
    return {"findings": findings, "suggestions": advisory}


async def document_workflow(
    workflow_data: dict[str, Any], *, chat: ChatFn | None, llm: dict[str, Any] | None
) -> dict[str, Any]:
    """Grounded markdown reference + optional LLM overview paragraph."""
    summary = _structure_summary(workflow_data)
    trigger_lines = [f"- `{t['id']}` ({t['type']})" for t in summary["triggers"]] or ["- (none)"]
    lines = [f"# {summary['name']}", "", "## Triggers", *trigger_lines, "", "## Steps"]
    for step in summary["steps"]:
        op = f" · op `{step['operation']}`" if step.get("operation") else ""
        feeds = (f" → feeds {', '.join('`' + f + '`' for f in step['feeds'])}"
                 if step["feeds"] else "")
        lines.append(f"- `{step['id']}` — **{step['type']}**{op}{feeds}")
    markdown = "\n".join(lines)

    overview = ""
    if chat is not None:
        try:
            message = await chat(llm, [
                {"role": "system", "content":
                    "You document automation workflows. Write 2-3 sentences"
                    " describing what this workflow accomplishes end to end."
                    " Use ONLY the structure provided; never invent steps."},
                {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
            ], temperature=0.3, max_tokens=300)
            overview = (message.get("content") or "").strip()
        except Exception:
            overview = ""  # doc stays useful without the LLM
    return {"markdown": markdown, "overview": overview, "structure": summary}


async def explain_workflow(
    workflow_data: dict[str, Any], *, chat: ChatFn, llm: dict[str, Any]
) -> dict[str, Any]:
    """Plain-language walkthrough grounded in the same structure facts."""
    summary = _structure_summary(workflow_data)
    message = await chat(llm, [
        {"role": "system", "content":
            "You explain automation workflows to non-developers. Walk through"
            " the flow step by step in <=180 words. Use ONLY the structure"
            " provided; never invent steps or behaviour."},
        {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
    ], temperature=0.3, max_tokens=500)
    return {"explanation": (message.get("content") or "").strip(), "structure": summary}
