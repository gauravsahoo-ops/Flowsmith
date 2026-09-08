"""RAG Pipeline node tests (Phase 13/14 → pgvector): chunking, optional deps,
store selection, ingestion, retrieval (threshold), synthesis and the
no-context path.

The node runs against the real ``pgvector`` store (PostgreSQL) per test;
``_retrieve``/collection helpers are exercised via the store contracts in
``test_vectorstores/test_pgvector.py``.
"""

from __future__ import annotations

import builtins
import logging
from typing import Any
import uuid

import httpx
import pytest

from app.engine import expressions
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.rag_pipeline import RAGPipelineNode, RAGParams, _chunk_text
from app.vectorstores import VectorStore, VectorStoreUnavailable
from app.vectorstores.pgvector import PgVectorStore

FAKE_MODEL = {"model": "fake-model", "base_url": "http://localhost:9/v1", "api_key": ""}


class FakeVector:
    def tolist(self) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeEmbedder:
    def encode(self, inputs: list[str]) -> list[FakeVector]:
        return [FakeVector() for _ in inputs]


class FakeStore(VectorStore):
    """Records calls; query() returns canned hits for threshold tests."""

    backend_name = "fake"

    def __init__(self, hits: list[dict[str, Any]] | None = None) -> None:
        self.hits = hits or []
        self.added: list[dict[str, Any]] = []
        self.ensure_calls: list[tuple[str, int]] = []

    def ensure_collection(self, name: str, dim: int) -> str:
        self.ensure_calls.append((name, dim))
        return "fake-handle"

    def add(
        self,
        handle: str,
        *,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> None:
        self.added.append({"documents": documents, "metadatas": metadatas, "ids": ids})

    def query(
        self,
        handle: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        return self.hits[:top_k]


async def _run_rag(
    params: dict,
    credentials: dict[str, Any] | None = None,
    monkeypatch=None,
    input_items: list[dict[str, Any]] | None = None,
    store: VectorStore | None = None,
    embedder: Any | None = None,
):
    items = input_items if input_items is not None else [{"task": "test"}]
    node = RAGPipelineNode()
    context = expressions.build_context(items, {}, "wf_1", "exec_1", credentials)
    p = RAGParams(**expressions.resolve(params, context))
    ctx = NodeContext(
        execution_id="exec_1",
        workflow_id="wf_1",
        logger=logging.getLogger("test"),
        http_client=httpx.AsyncClient(),
        credentials=credentials or {},
    )
    if monkeypatch is not None:
        if store is not None:
            monkeypatch.setattr("app.nodes.rag_pipeline.get_vector_store", lambda: store)
        monkeypatch.setattr(
            "app.nodes.rag_pipeline._get_embedding_model",
            lambda name: embedder if embedder is not None else FakeEmbedder(),
        )
    return await node.run(ctx, p, items)


def _pgvector_store(tmp_path=None) -> PgVectorStore:  # tmp_path kept for call-site compat
    return PgVectorStore()


# --- pure helpers ---------------------------------------------------------


def test_chunk_text_overlap():
    text = "0123456789" * 5  # 50 chars
    chunks = _chunk_text(text, 20, 5)
    assert chunks[0] == text[:20]
    assert chunks[1] == text[15:35]  # overlaps the previous chunk by 5
    assert chunks[-1].endswith(text[-1])


# --- node behaviour -------------------------------------------------------


async def test_missing_llm_credential_fails():
    with pytest.raises(NodeExecutionError) as ei:
        await _run_rag({"query": "What is the capital of France?"})
    assert ei.value.code == "CREDENTIALS_REQUIRED"


async def test_optional_deps_missing_reports_friendly_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("sentence_transformers"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(NodeExecutionError) as ei:
        await _run_rag({"query": "x"}, {"llm": FAKE_MODEL})
    assert ei.value.code == "OPTIONAL_DEPS_MISSING"


async def test_unknown_store_and_unavailable_errors(monkeypatch):
    def raise_unknown():
        raise ValueError("Unknown vector store 'nope' (available: pgvector)")

    monkeypatch.setattr("app.nodes.rag_pipeline.get_vector_store", raise_unknown)
    with pytest.raises(NodeExecutionError) as ei:
        await _run_rag({"query": "x"}, {"llm": FAKE_MODEL}, monkeypatch)
    assert ei.value.code == "UNKNOWN_VECTOR_STORE"

    class BrokenStore:
        def ensure_collection(self, name, dim):
            raise VectorStoreUnavailable("chroma not installed")

        def add(self, **kwargs):
            raise AssertionError("should not reach add")

        def query(self, handle, query_embedding, top_k):
            raise AssertionError("should not reach query")

    monkeypatch.setattr("app.nodes.rag_pipeline.get_vector_store", lambda: BrokenStore())
    with pytest.raises(NodeExecutionError) as ei:
        await _run_rag({"query": "x"}, {"llm": FAKE_MODEL}, monkeypatch)
    assert ei.value.code == "OPTIONAL_DEPS_MISSING"


async def test_missing_query_fails(tmp_path, monkeypatch):
    import uuid
    with pytest.raises(NodeExecutionError) as ei:
        await _run_rag(
            {"source_type": "text", "source": "ignored", "collection_name": f"rag_q_missing_{uuid.uuid4().hex[:6]}"},
            {"llm": FAKE_MODEL}, monkeypatch, input_items=[], store=_pgvector_store(),
        )
    assert ei.value.code == "MISSING_QUERY"


async def test_ingest_retrieve_generate_happy_path(tmp_path, monkeypatch):
    import uuid
    async def fake_chat(credential, messages, **kwargs):
        return {"content": "Paris"}

    monkeypatch.setattr("app.nodes.rag_pipeline.chat_completion", fake_chat)

    coll = f"rag_happy_{uuid.uuid4().hex[:6]}"
    result = await _run_rag(
        {
            "source_type": "text",
            "source": "The capital of France is Paris.",
            "query": "What is the capital of France?",
            "collection_name": coll,
        },
        {"llm": FAKE_MODEL},
        monkeypatch,
        store=_pgvector_store(),
    )
    item = result.items_for("main")[0]
    assert item["answer"] == "Paris"
    assert item["chunks_used"] == 1
    assert item["chunks"][0]["content"].startswith("The capital")


async def test_file_ingestion(tmp_path, monkeypatch):
    import uuid
    src = tmp_path / "kb.txt"
    src.write_text("RAG pipelines embed chunks and retrieve them.", encoding="utf-8")

    async def fake_chat(credential, messages, **kwargs):
        return {"content": "embedded chunks"}

    monkeypatch.setattr("app.nodes.rag_pipeline.chat_completion", fake_chat)

    coll = f"rag_file_{uuid.uuid4().hex[:6]}"
    result = await _run_rag(
        {
            "source_type": "file",
            "source": str(src),
            "query": "what does rag do?",
            "collection_name": coll,
        },
        {"llm": FAKE_MODEL},
        monkeypatch,
        store=_pgvector_store(),
    )
    item = result.items_for("main")[0]
    assert item["answer"] == "embedded chunks"
    assert item["chunks_used"] == 1
    assert item["chunks"][0]["metadata"]["source"] == "file"


async def test_no_relevant_context_returns_without_llm(tmp_path, monkeypatch):
    import uuid
    result = await _run_rag(
        {"query": "asking about an empty knowledge base", "collection_name": f"rag_none_{uuid.uuid4().hex[:6]}"},
        {"llm": FAKE_MODEL},
        monkeypatch,
        store=_pgvector_store(),
    )
    item = result.items_for("main")[0]
    assert item["answer"] == "No relevant context found."
    assert item["chunks_used"] == 0


async def test_threshold_filters_low_similarity(monkeypatch):
    async def fake_chat(credential, messages, **kwargs):
        return {"content": "synthesis"}

    monkeypatch.setattr("app.nodes.rag_pipeline.chat_completion", fake_chat)

    store = FakeStore(hits=[
        {"content": "best", "metadata": {}, "similarity": 0.9},
        {"content": "meh", "metadata": {}, "similarity": 0.2},
        {"content": "ok", "metadata": {}, "similarity": 0.5},
    ])

    result = await _run_rag(
        {"query": "q", "collection_name": "rag_fake", "similarity_threshold": 0.3},
        {"llm": FAKE_MODEL},
        monkeypatch,
        store=store,
    )
    item = result.items_for("main")[0]
    assert item["chunks_used"] == 2
    assert [c["content"] for c in item["chunks"]] == ["best", "ok"]  # best-first, filtered


async def test_passes_embedding_dimension_from_model(monkeypatch):
    store = FakeStore()
    await _run_rag(
        {"query": "q", "collection_name": "rag_fake_dim"},
        {"llm": FAKE_MODEL},
        monkeypatch,
        store=store,
    )
    assert store.ensure_calls == [("rag_fake_dim", 3)]  # FakeEmbedder produces 3-d vectors