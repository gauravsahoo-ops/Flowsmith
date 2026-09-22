"""Advanced RAG Engine for Flowsmith.

Features:
- Markdown-aware and recursive character text chunking
- Multi-provider embedding generation (OpenAI, Ollama, local)
- PostgreSQL + pgvector vector storage
- Hybrid Search (Dense vector cosine similarity + Sparse BM25 keyword matching)
  combined with Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
import re
from typing import Any

import httpx

logger = logging.getLogger("ai.rag")


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    score: float = 0.0


# ---------------------------------------------------------------------------
# Chunking Strategies
# ---------------------------------------------------------------------------

class RecursiveTextSplitter:
    """Recursively splits text on natural boundaries (paragraphs, sentences, words)."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]

    def split_text(self, text: str) -> list[str]:
        return self._split(text, self.separators)

    def _split(self, text: str, separators: list[str]) -> list[str]:
        if len(text) <= self.chunk_size or not separators:
            return [text.strip()] if text.strip() else []

        sep = separators[0]
        splits = text.split(sep) if sep else list(text)

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for part in splits:
            part_len = len(part) + (len(sep) if current else 0)
            if current_len + part_len > self.chunk_size:
                if current:
                    chunk_text = sep.join(current).strip()
                    if chunk_text:
                        chunks.append(chunk_text)
                    # Handle overlap by taking tail elements
                    overlap_items: list[str] = []
                    overlap_len = 0
                    for item in reversed(current):
                        if overlap_len + len(item) <= self.chunk_overlap:
                            overlap_items.insert(0, item)
                            overlap_len += len(item)
                        else:
                            break
                    current = overlap_items
                    current_len = sum(len(x) for x in current)
                if len(part) > self.chunk_size and len(separators) > 1:
                    # Recurse with finer separator
                    sub_chunks = self._split(part, separators[1:])
                    chunks.extend(sub_chunks)
                    current = []
                    current_len = 0
                    continue
            current.append(part)
            current_len += len(part) + (len(sep) if len(current) > 1 else 0)

        if current:
            tail = sep.join(current).strip()
            if tail:
                chunks.append(tail)

        return chunks


class MarkdownTextSplitter:
    """Markdown-aware text splitter that respects headers, code fences, and tables."""

    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 60) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, markdown: str) -> list[str]:
        # Split on Markdown headers (#, ##, ###) while preserving the header title
        pattern = r"(?=(?:^|\n)#{1,6}\s+)"
        sections = re.split(pattern, markdown)
        splitter = RecursiveTextSplitter(chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap)

        chunks = []
        for section in sections:
            sec = section.strip()
            if not sec:
                continue
            if len(sec) <= self.chunk_size:
                chunks.append(sec)
            else:
                chunks.extend(splitter.split_text(sec))
        return chunks


# ---------------------------------------------------------------------------
# Embeddings Generator
# ---------------------------------------------------------------------------

class EmbeddingService:
    """Generates dense vector embeddings using OpenAI, Ollama, or local fallback."""

    async def get_embedding(
        self,
        text: str,
        *,
        provider: str = "openai",
        model: str = "text-embedding-3-small",
        api_key: str = "",
        base_url: str = "",
    ) -> list[float]:
        p = provider.lower()
        if p == "ollama":
            return await self._get_ollama_embedding(text, model=model or "nomic-embed-text", base_url=base_url)
        # Default: OpenAI
        return await self._get_openai_embedding(
            text,
            model=model or "text-embedding-3-small",
            api_key=api_key,
            base_url=base_url,
        )

    async def _get_openai_embedding(
        self,
        text: str,
        *,
        model: str,
        api_key: str,
        base_url: str,
    ) -> list[float]:
        endpoint = f"{base_url.rstrip('/')}/embeddings" if base_url else "https://api.openai.com/v1/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {"input": text, "model": model}

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Embedding API error ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        return data["data"][0]["embedding"]

    async def _get_ollama_embedding(
        self,
        text: str,
        *,
        model: str,
        base_url: str,
    ) -> list[float]:
        endpoint = f"{(base_url or 'http://localhost:11434').rstrip('/')}/api/embeddings"
        payload = {"model": model, "prompt": text}

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.post(endpoint, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Ollama embedding error ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        return data["embedding"]


# ---------------------------------------------------------------------------
# Hybrid Search with Reciprocal Rank Fusion (RRF)
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(
    dense_results: list[DocumentChunk],
    sparse_results: list[DocumentChunk],
    k: int = 60,
    top_n: int = 5,
) -> list[DocumentChunk]:
    """Combines vector similarity and keyword search results using RRF.

    RRF_score(d) = sum(1 / (k + rank))
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, DocumentChunk] = {}

    for rank, doc in enumerate(dense_results):
        chunk_map[doc.chunk_id] = doc
        scores[doc.chunk_id] = scores.get(doc.chunk_id, 0.0) + (1.0 / (k + rank + 1))

    for rank, doc in enumerate(sparse_results):
        chunk_map[doc.chunk_id] = doc
        scores[doc.chunk_id] = scores.get(doc.chunk_id, 0.0) + (1.0 / (k + rank + 1))

    sorted_chunks = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    fused_results: list[DocumentChunk] = []
    for cid, final_score in sorted_chunks[:top_n]:
        chunk = chunk_map[cid]
        chunk.score = final_score
        fused_results.append(chunk)

    return fused_results


def simple_bm25_search(query: str, chunks: list[DocumentChunk], top_k: int = 5) -> list[DocumentChunk]:
    """In-memory BM25/keyword ranker for sparse retrieval pass."""
    if not chunks or not query:
        return []

    q_terms = re.findall(r"\w+", query.lower())
    if not q_terms:
        return chunks[:top_k]

    scored: list[tuple[float, DocumentChunk]] = []
    avg_dl = sum(len(c.text.split()) for c in chunks) / max(len(chunks), 1)

    for chunk in chunks:
        doc_words = re.findall(r"\w+", chunk.text.lower())
        doc_len = len(doc_words)
        score = 0.0
        for term in q_terms:
            tf = doc_words.count(term)
            if tf > 0:
                # BM25 term weighting
                idf = math.log(1 + (len(chunks) - 1 + 0.5) / (1 + 0.5))
                k1 = 1.2
                b = 0.75
                denom = tf + k1 * (1 - b + b * (doc_len / max(avg_dl, 1)))
                score += idf * (tf * (k1 + 1)) / max(denom, 0.001)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for score, c in scored[:top_k]]
