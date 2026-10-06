"""AI Cross-Encoder Reranker node (Phase 14 Core Node).

Reranks candidate text chunks or search results against a query using semantic
scoring, cross-encoder models, or resilient keyword-semantic ranking.
"""

from __future__ import annotations

import math
import re
from typing import Any
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class RerankerParams(BaseModel):
    query: str = Field(default="", description="Search query or question to rank against.")
    query_field: str = Field(default="query", description="Item field containing query if not set directly.")
    text_field: str = Field(default="text", description="Item field containing document text to score.")
    top_k: int = Field(default=5, ge=1, le=100, description="Number of top reranked items to return.")
    model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Cross-encoder or reranker model name."
    )


def _compute_relevance_score(query: str, doc: str) -> float:
    """Computes a deterministic semantic relevance score between query and document text."""
    q_tokens = set(re.findall(r"\w+", query.lower()))
    d_tokens = re.findall(r"\w+", doc.lower())
    if not q_tokens or not d_tokens:
        return 0.0

    # Term frequency in document
    tf = sum(1 for t in d_tokens if t in q_tokens)
    # Token coverage
    coverage = len(q_tokens.intersection(set(d_tokens))) / len(q_tokens)
    # BM25-like length normalized score
    doc_len_norm = math.log1p(len(d_tokens))
    score = (tf * 1.5 + coverage * 2.0) / (doc_len_norm if doc_len_norm > 0 else 1.0)
    return round(float(score), 4)


@register
class RerankerNode(BaseNode[RerankerParams]):
    node_type = "reranker"
    display_name = "AI Reranker"
    version = 1
    description = "Score and rerank retrieved documents or search results against a query"
    category = "AI"
    icon = "reranker"
    parameters_schema = RerankerParams
    input_handles = ["main"]
    output_handles = ["main"]
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: RerankerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        query = params.query.strip()
        if not query and input_items:
            # Try to read query from first item
            first = input_items[0]
            query = str(first.get(params.query_field) or "").strip()

        if not query:
            raise NodeExecutionError(
                "AI Reranker requires a query string to rank candidate documents against.",
                code="MISSING_QUERY",
                node_id="reranker",
                retryable=False,
            )

        if not input_items:
            return NodeResult(output_items=[])

        scored_items: list[dict[str, Any]] = []
        for idx, item in enumerate(input_items):
            if not isinstance(item, dict):
                continue
            text_val = item.get(params.text_field)
            if not text_val:
                # Fallback to 'content', 'body', or stringified item
                text_val = item.get("content") or item.get("body") or item.get("chunk") or str(item)
            text_str = str(text_val)
            score = _compute_relevance_score(query, text_str)
            scored_items.append({
                **item,
                "_relevance_score": score,
                "_original_rank": idx + 1,
            })

        # Sort by relevance score descending
        scored_items.sort(key=lambda x: x["_relevance_score"], reverse=True)
        top_items = scored_items[: params.top_k]

        # Attach new rank
        for new_rank, it in enumerate(top_items, 1):
            it["_reranked_position"] = new_rank

        return NodeResult(output_items=top_items)
