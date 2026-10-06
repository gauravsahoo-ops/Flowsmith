"""String Tools node (Phase 7 Data Transformation).

Deterministic string/number/regex toolkit covering the most common
formatter operations without resorting to Code nodes:

- case: upper / lower / title / trim / slug
- slice / replace / split / join / length
- regex_extract (first match group) / regex_match (bool) / regex_replace
- to_number / format_number / concat

Operates per input item over a source field; result written to
``destination`` (default: same field). Pure function, idempotent.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class StringToolsParams(BaseModel):
    operation: Literal[
        "upper", "lower", "title", "trim", "slug", "slice", "replace",
        "split", "join", "length", "regex_extract", "regex_match",
        "regex_replace", "to_number", "concat",
    ] = Field(default="trim")
    source: str = Field(default="text", description="Source field (dot path).")
    destination: str = Field(default="", description="Destination field (empty = overwrite source).")
    # Generic operands
    pattern: str = Field(default="", description="Regex pattern / search string.")
    replacement: str = Field(default="", description="Replacement for replace/regex_replace.")
    start: int = Field(default=0)
    end: int | None = Field(default=None)
    separator: str = Field(default=",")
    extra: str = Field(default="", description="Second operand for concat.")
    case_insensitive: bool = Field(default=False)


def _read(item: dict[str, Any], path: str) -> Any:
    if not path:
        return ""
    cur: Any = item
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _write(item: dict[str, Any], path: str, value: Any) -> None:
    parts = (path or "").split(".")
    cur = item
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _apply(op: str, value: Any, p: StringToolsParams) -> Any:
    text = "" if value is None else (value if isinstance(value, str) else str(value))
    flags = re.IGNORECASE if p.case_insensitive else 0
    if op == "upper":
        return text.upper()
    if op == "lower":
        return text.lower()
    if op == "title":
        return text.title()
    if op == "trim":
        return text.strip()
    if op == "slug":
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        return slug
    if op == "slice":
        return text[p.start:p.end]
    if op == "replace":
        if p.case_insensitive:
            return re.sub(re.escape(p.pattern), p.replacement, text, flags=re.IGNORECASE)
        return text.replace(p.pattern, p.replacement)
    if op == "split":
        return text.split(p.separator)
    if op == "join":
        if isinstance(value, list):
            return p.separator.join(str(v) for v in value)
        return text
    if op == "length":
        return len(value) if isinstance(value, (list, str)) else len(text)
    if op == "regex_extract":
        if not p.pattern:
            raise NodeExecutionError("regex_extract needs a pattern.", code="STR_MISSING_PATTERN", retryable=False)
        m = re.search(p.pattern, text, flags)
        if not m:
            return ""
        return m.group(1) if m.lastindex else m.group(0)
    if op == "regex_match":
        if not p.pattern:
            raise NodeExecutionError("regex_match needs a pattern.", code="STR_MISSING_PATTERN", retryable=False)
        return bool(re.search(p.pattern, text, flags))
    if op == "regex_replace":
        if not p.pattern:
            raise NodeExecutionError("regex_replace needs a pattern.", code="STR_MISSING_PATTERN", retryable=False)
        return re.sub(p.pattern, p.replacement, text, flags=flags)
    if op == "to_number":
        try:
            num = float(text.strip())
            return int(num) if num.is_integer() else num
        except ValueError as exc:
            raise NodeExecutionError(f"Cannot convert '{text}' to number.", code="STR_NAN", retryable=False) from exc
    if op == "concat":
        return text + p.extra
    return text


@register
class StringToolsNode(BaseNode[StringToolsParams]):
    node_type = "string_tools"
    display_name = "String Tools"
    version = 1
    description = "Format, split, match and convert strings and numbers."
    category = "Transform"
    icon = "string_tools"
    parameters_schema = StringToolsParams

    async def run(self, ctx: NodeContext, params: StringToolsParams, input_items: list[dict[str, Any]]) -> NodeResult:
        out: list[dict[str, Any]] = []
        for item in input_items:
            value = _read(item, params.source)
            result = _apply(params.operation, value, params)
            nxt = dict(item)
            _write(nxt, params.destination or params.source, result)
            out.append(nxt)
        return NodeResult(output_items=out)
