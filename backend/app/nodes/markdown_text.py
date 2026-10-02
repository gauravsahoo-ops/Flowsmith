"""Markdown text node.

Minimal markdown helpers with stdlib only (no extra dependency):
markdown-to-text stripping and a small markdown-to-HTML subset
(headings, bold, italic, code, links, lists, paragraphs).
"""

from __future__ import annotations

import html
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class MarkdownTextParams(BaseModel):
    operation: Literal["to_text", "to_html"] = Field(default="to_text")
    text: str = Field(default="", description="Markdown source (empty = first input item text).")
    field: str = Field(default="", description="Field to read from each input item when text is empty.")


def _read_source(params: MarkdownTextParams, items: list[dict[str, Any]]) -> str:
    if params.text:
        return params.text
    if not items:
        return ""
    first = items[0]
    if params.field:
        cur: Any = first
        for part in params.field.split("."):
            cur = cur.get(part, "") if isinstance(cur, dict) else ""
        return str(cur or "")
    if isinstance(first, dict):
        for key in ("text", "markdown", "content", "json"):
            if key in first and isinstance(first[key], str):
                return first[key]
        return str(first)
    return str(first)


def _md_to_text(md: str) -> str:
    out = re.sub(r"```.*?```", "", md, flags=re.S)
    out = re.sub(r"^#{1,6}\s*", "", out, flags=re.M)
    out = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", out)
    out = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", out)
    out = re.sub(r"(\*\*|__)(.*?)\1", r"\2", out)
    out = re.sub(r"(\*|_)(.*?)\1", r"\2", out)
    out = re.sub(r"`([^`]*)`", r"\1", out)
    out = re.sub(r"^\s*[-*+]\s+", "", out, flags=re.M)
    out = re.sub(r"^\s*\d+\.\s+", "", out, flags=re.M)
    out = re.sub(r"^>\s?", "", out, flags=re.M)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _md_to_html(md: str) -> str:
    esc = html.escape(md)
    lines = esc.splitlines()
    html_lines: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading:
            level = len(heading.group(1))
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h{level}>{heading.group(2)}</h{level}>")
            continue
        if re.match(r"^([-*+])\s+", stripped):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{re.sub(r'^[ -*+]\s+', '', stripped)}</li>")
            continue
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        html_lines.append(f"<p>{stripped}</p>")
    if in_list:
        html_lines.append("</ul>")
    body = "\n".join(html_lines)
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(r"`([^`]+)`", r"<code>\1</code>", body)
    return body


@register
class MarkdownTextNode(BaseNode[MarkdownTextParams]):
    node_type = "markdown_text"
    display_name = "Markdown"
    version = 1
    description = "Convert markdown to plain text or simple HTML."
    category = "Transform"
    icon = "markdown_text"
    parameters_schema = MarkdownTextParams

    async def run(
        self,
        ctx: NodeContext,
        params: MarkdownTextParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        src = _read_source(params, input_items or [])
        if params.operation == "to_html":
            return NodeResult(output_items=[{"html": _md_to_html(src)}])
        return NodeResult(output_items=[{"text": _md_to_text(src)}])
