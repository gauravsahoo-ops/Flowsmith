"""Output parser node (Batch C, original implementation).

Parse AI/model text output into structured items: extract JSON
(fenced or raw), split lines, or pull fields with dot paths. Pure
local transform for chaining ai/ai_agent into downstream nodes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class OutputParserParams(BaseModel):
    mode: Literal["json", "lines", "fields"] = Field(default="json")
    text: str = Field(default="", description="Model text (empty = first input item response/content/text).")
    fields: list[str] = Field(default_factory=list, description="Dot paths to keep in fields mode.")
    strict: bool = Field(default=False, description="Fail on invalid JSON instead of passthrough.")


def _source(params: OutputParserParams, items: list[dict[str, Any]]) -> str:
    if params.text:
        return params.text
    if not items:
        return ""
    first = items[0] if isinstance(items[0], dict) else {}
    for key in ("response", "content", "text", "output", "answer"):
        if isinstance(first.get(key), str) and first[key]:
            return first[key]
    return str(first)


def _extract_json_blob(src: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", src, flags=re.S | re.I)
    if fenced:
        return fenced.group(1).strip()
    start = min([i for i in (src.find("{"), src.find("[")) if i >= 0], default=-1)
    if start < 0:
        return src.strip()
    depth, end = 0, -1
    for i in range(start, len(src)):
        if src[i] in "{[":
            depth += 1
        elif src[i] in "}]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    return src[start:end] if end > 0 else src[start:].strip()


def _pick(item: Any, path: str) -> Any:
    cur: Any = item
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


@register
class OutputParserNode(BaseNode[OutputParserParams]):
    node_type = "output_parser"
    display_name = "Output Parser"
    version = 1
    description = "Parse model text into JSON, lines, or fields."
    category = "AI"
    icon = "🧩"
    parameters_schema = OutputParserParams

    async def run(
        self,
        ctx: NodeContext,
        params: OutputParserParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        src = _source(params, input_items or [])
        if params.mode == "lines":
            lines = [ln.strip() for ln in src.splitlines() if ln.strip()]
            return NodeResult(output_items=[{"line": ln, "index": i} for i, ln in enumerate(lines)] or [{"line": ""}])
        if params.mode == "fields":
            first = (input_items or [{}])[0]
            try:
                parsed: Any = json.loads(_extract_json_blob(src)) if src.strip() else {}
            except Exception:
                parsed = {}
            base = parsed if isinstance(parsed, dict) else {"value": parsed}
            if isinstance(first, dict):
                base = {**first, **base}
            if not params.fields:
                return NodeResult(output_items=[base] if isinstance(base, dict) else [{"value": base}])
            return NodeResult(output_items=[{f: _pick(base, f) for f in params.fields}])
        # json mode
        blob = _extract_json_blob(src)
        try:
            parsed = json.loads(blob) if blob else {}
        except Exception:
            if params.strict:
                from app.engine.errors import NodeExecutionError

                raise NodeExecutionError(
                    "Model output was not valid JSON.",
                    code="OUTPUT_PARSE_ERROR", node_id="output_parser", retryable=False,
                )
            return NodeResult(output_items=[{"text": src}])
        if isinstance(parsed, list):
            return NodeResult(output_items=[it if isinstance(it, dict) else {"value": it} for it in parsed] or [{"value": None}])
        return NodeResult(output_items=[parsed] if isinstance(parsed, dict) else [{"value": parsed}])
