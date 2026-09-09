"""Text splitter node (Batch C, original implementation).

Split long text into overlapping chunks for RAG ingestion: by
characters, lines, or paragraphs. Pure local transform, no side effects.
Stdlib only — no extra dependency.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class TextSplitterParams(BaseModel):
    mode: Literal["characters", "lines", "paragraphs"] = Field(default="characters")
    text: str = Field(default="", description="Text to split (empty = first input item text).")
    field: str = Field(default="", description="Field to read from each input item when text is empty.")
    chunk_size: int = Field(default=1000, ge=50, le=20000)
    overlap: int = Field(default=100, ge=0, le=5000)
    max_chunks: int = Field(default=200, ge=1, le=2000)


def _source(params: TextSplitterParams, items: list[dict[str, Any]]) -> str:
    if params.text:
        return params.text
    if not items:
        return ""
    first = items[0] if isinstance(items[0], dict) else {}
    if params.field:
        cur: Any = first
        for part in params.field.split("."):
            cur = cur.get(part, "") if isinstance(cur, dict) else ""
        return str(cur or "")
    for key in ("text", "content", "body", "markdown"):
        if isinstance(first.get(key), str) and first[key]:
            return first[key]
    return str(first)


def _split_units(src: str, mode: str) -> tuple[list[str], str]:
    if mode == "lines":
        return src.splitlines(keepends=True), ""
    if mode == "paragraphs":
        parts = [p.strip() for p in src.split("\n\n")]
        return [p + "\n\n" for p in parts if p], ""
    return [src], ""


@register
class TextSplitterNode(BaseNode[TextSplitterParams]):
    node_type = "text_splitter"
    display_name = "Text Splitter"
    version = 1
    description = "Split text into overlapping chunks for RAG."
    category = "AI"
    icon = "✂️"
    parameters_schema = TextSplitterParams

    async def run(
        self,
        ctx: NodeContext,
        params: TextSplitterParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        src = _source(params, input_items or "")
        if not src.strip():
            return NodeResult(output_items=[{"chunk": "", "index": 0, "total": 1}])
        overlap = min(params.overlap, params.chunk_size - 1)
        if params.mode == "characters":
            chunks: list[str] = []
            step = params.chunk_size - overlap
            for start in range(0, len(src), step):
                chunks.append(src[start : start + params.chunk_size])
                if len(chunks) >= params.max_chunks:
                    break
            total = len(chunks)
            return NodeResult(output_items=[{"chunk": c, "index": i, "total": total} for i, c in enumerate(chunks)])
        units, _ = _split_units(src, params.mode)
        chunks = []
        current = ""
        for unit in units:
            if len(current) + len(unit) > params.chunk_size and current:
                chunks.append(current)
                current = current[-overlap:] if overlap else ""
                if len(chunks) >= params.max_chunks:
                    break
            current += unit
        if current and len(chunks) < params.max_chunks:
            chunks.append(current)
        total = len(chunks) or 1
        if not chunks:
            chunks = [src[: params.chunk_size]]
        return NodeResult(output_items=[{"chunk": c, "index": i, "total": total} for i, c in enumerate(chunks[: params.max_chunks])])
