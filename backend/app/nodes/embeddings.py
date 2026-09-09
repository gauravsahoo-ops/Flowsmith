"""Embeddings node (Batch C, original implementation).

Turn input texts into embedding vectors via the shared RAG service
(`app.rag.embed_texts`): real sentence-transformers vectors when the
optional AI extra is installed, deterministic dev fallback otherwise
(production refuses the fallback). Pairs with Text Splitter upstream
and pgvector storage downstream.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.rag import DEFAULT_EMBEDDING_MODEL


class EmbeddingsParams(BaseModel):
    texts: list[str] = Field(default_factory=list, description="Texts to embed (empty = read from items).")
    field: str = Field(default="chunk", description="Item field to read when texts is empty.")
    model: str = Field(default=DEFAULT_EMBEDDING_MODEL, description="Embedding model name.")
    max_items: int = Field(default=100, ge=1, le=1000)


def _read_texts(params: EmbeddingsParams, items: list[dict[str, Any]]) -> list[str]:
    if params.texts:
        return [str(t) for t in params.texts[: params.max_items] if str(t or "").strip()]
    out: list[str] = []
    for item in items[: params.max_items]:
        if not isinstance(item, dict):
            continue
        cur: Any = item
        if params.field:
            for part in params.field.split("."):
                cur = cur.get(part, "") if isinstance(cur, dict) else ""
        if isinstance(cur, str) and cur.strip():
            out.append(cur)
        elif cur:
            out.append(str(cur))
    return out


@register
class EmbeddingsNode(BaseNode[EmbeddingsParams]):
    node_type = "embeddings"
    display_name = "Embeddings"
    version = 1
    description = "Embed texts into vectors for RAG retrieval."
    category = "AI"
    icon = "🧠"
    parameters_schema = EmbeddingsParams
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: EmbeddingsParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        from app.rag import embed_texts

        texts = _read_texts(params, input_items or [])
        if not texts:
            return NodeResult(output_items=[{"embedding": [], "dim": 0, "model": params.model}])
        vectors = embed_texts(texts, params.model)
        return NodeResult(
            output_items=[
                {"text": text, "embedding": vec, "dim": len(vec), "model": params.model}
                for text, vec in zip(texts, vectors)
            ]
        )
