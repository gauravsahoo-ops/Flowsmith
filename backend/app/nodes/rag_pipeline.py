"""RAG Pipeline node (Phase 13-14, spec 20): vector search + embeddings +
LLM synthesis in one node.

Features:
- Document ingestion from text, files, or URLs
- Automatic chunking with overlap
- Embedding generation via sentence-transformers
- PostgreSQL + pgvector vector storage (app/vectorstores)

The embedding dependency (`sentence-transformers`) is an optional extra
(backend/requirements-ai.txt): this module imports cleanly on a base
install, and the node reports a friendly `OPTIONAL_DEPS_MISSING` error
when run without it. The default pgvector store itself needs nothing
extra beyond the configured PostgreSQL database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.ai.client import chat_completion, LLMError
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NON_IDEMPOTENT, BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.vectorstores import VectorStoreUnavailable, get_vector_store


class RAGParams(BaseModel):
    # Ingestion
    source_type: str = Field(
        default="text",
        pattern="^(text|file|url)$",
        description="Source type: inline text, local file path, or URL to fetch.",
    )
    source: str = Field(
        default="",
        description="Text content, file path, or URL depending on source_type.",
    )
    collection_name: str = Field(
        default="rag_default",
        description="Vector store collection name for this knowledge base.",
    )
    chunk_size: int = Field(
        default=500,
        ge=100,
        le=2000,
        description="Target size of each chunk in characters.",
    )
    chunk_overlap: int = Field(
        default=50,
        ge=0,
        le=500,
        description="Overlap between consecutive chunks.",
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformers model name for embeddings.",
    )

    # Retrieval
    top_k: int = Field(
        default=4,
        ge=1,
        le=20,
        description="Number of chunks to retrieve.",
    )
    similarity_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity for retrieved chunks.",
    )

    # Generation
    query: str = Field(
        default="",
        description="The question or task for the RAG pipeline.",
    )
    system_prompt: str = Field(
        default="Answer the question using only the provided context. If the answer is not in the context, say you don't know.",
        description="System prompt for the LLM.",
    )
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=4000)


# Module-level cache for the embedding model. The heavy embedding
# dependency (`sentence-transformers`) is an optional extra
# (backend/requirements-ai.txt): imported lazily at run time, so this
# module always imports cleanly on a base install.
_embedding_model: Any = None


def _get_embedding_model(model_name: str) -> Any:
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]

        _embedding_model = SentenceTransformer(model_name)
    return _embedding_model


def _embed_list(model: Any, texts: list[str]) -> list[list[float]]:
    """Encode texts with the sentence-transformers model into plain floats
    (handles numpy arrays and plain lists alike)."""
    vectors = model.encode(texts)
    return [
        [float(x) for x in (v.tolist() if hasattr(v, "tolist") else v)]
        for v in vectors
    ]


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks using RecursiveTextSplitter."""
    from app.ai.rag import RecursiveTextSplitter
    return RecursiveTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap).split_text(text)


async def _load_source_text(source_type: str, source: str, ctx: Any | None = None) -> str:
    """Resolve the source parameter to plain text.

    Supports two file modes (Phase 20):
    - ``file:<id>`` — S3/local object-store file (workspace-scoped, auth-checked)
    - ``/absolute/path`` — legacy local filesystem path (development only)
    """
    if source_type == "text":
        return source
    if source_type == "file":
        # Object-store file reference (preferred, workspace-aware)
        if source.startswith("file:"):
            file_id = source[5:].strip()
            if not file_id:
                raise ValueError("file: reference missing id")
            from app.db import get_session
            from app.models import FileRecord

            db = get_session()
            try:
                rec = db.get(FileRecord, file_id)
                if rec is None:
                    raise FileNotFoundError(f"File not found: {file_id}")
                # Workspace isolation: file must belong to the run's workspace
                # or be a personal file owned by the run's user.
                if ctx is not None and hasattr(ctx, "workspace_id"):
                    run_ws = getattr(ctx, "workspace_id", None)
                    run_user = int(getattr(ctx, "user_id", 0) or 0)
                    if rec.workspace_id is not None and rec.workspace_id != run_ws:
                        # Allow cross-workspace only when the file is personal
                        # and owned by the runner (already checked below).
                        raise PermissionError(f"File {file_id} belongs to a different workspace.")
                    if rec.owner_user_id != run_user and rec.workspace_id != run_ws:
                        # Fallback membership check for shared workspaces
                        if rec.workspace_id is not None:
                            from sqlalchemy import select as _select
                            from app.models import WorkspaceMember as _WM
                            member = db.scalar(
                                _select(_WM).where(
                                    _WM.workspace_id == rec.workspace_id,
                                    _WM.user_id == run_user,
                                )
                            )
                            if member is None:
                                raise PermissionError(f"No access to file {file_id}.")
                from app.objectstore.factory import get_object_store

                raw = get_object_store().get(rec.object_key)
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    return raw.decode("utf-8", errors="replace")
            finally:
                db.close()
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {source}")
        return path.read_text(encoding="utf-8")
    if source_type == "url":
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(source)
            resp.raise_for_status()
            return resp.text
    raise ValueError(f"Unknown source_type: {source_type}")


def _source_metadata(source_type: str, source: str) -> dict[str, Any]:
    if source_type == "file":
        if source.startswith("file:"):
            return {"file_id": source[5:].strip(), "source": "object_store"}
        return {"file_path": str(Path(source))}
    if source_type == "url":
        return {"url": source}
    return {}


def _store_unavailable(error: VectorStoreUnavailable) -> NodeExecutionError:
    return NodeExecutionError(
        str(error), code="OPTIONAL_DEPS_MISSING", node_id="rag_pipeline", retryable=False,
    )


SYSTEM_PROMPT_TEMPLATE = """{system_prompt}

Context from knowledge base (each block is labeled with a citation ref like [1]):
{context}

Answer using only the provided context. Cite the refs you used inline (e.g. [1]).
If the answer is not in the context, say you don't know."""


def _resolve_collection(ctx: NodeContext, name: str):
    """Tenant-safe collection resolution (Phase 18).

    With run identity (the normal worker path), collections resolve
    through the RagCollection registry — raw names never touch the
    store directly, and missing collections auto-provision inside the
    run's tenant scope. Without identity (bare engine tests), fall back
    to the legacy direct-name behaviour so local graphs keep working.
    Returns (store, physical_store_name, registry_record_or_None).
    """
    store = get_vector_store()
    if not ctx.user_id:
        return store, name, None

    from app.db import get_session
    from app.rag import RagAccess, create_collection, list_collections

    db = get_session()
    try:
        uid = int(ctx.user_id)
        access = RagAccess(user_id=uid, workspace_id=ctx.workspace_id)
        matches = [
            r for r in list_collections(db, access)
            if r.name == name and (
                r.workspace_id == ctx.workspace_id
                or (r.workspace_id is None and r.owner_user_id == uid)
            )
        ]
        rec = matches[0] if matches else None
        if rec is None:
            rec = create_collection(
                db, name=name,
                access=RagAccess(
                    user_id=uid,
                    workspace_id=ctx.workspace_id,
                    editable_workspaces={ctx.workspace_id} if ctx.workspace_id else set(),
                ),
            )
        return store, rec.store_name, rec
    finally:
        db.close()


@register
class RAGPipelineNode(BaseNode[RAGParams]):
    node_type = "rag_pipeline"
    display_name = "RAG Pipeline"
    version = 1
    description = "Ingest documents, embed, retrieve relevant chunks, and synthesize answer with LLM."
    category = "AI"
    icon = "📚"
    parameters_schema = RAGParams
    credential_types = ["llm"]
    # Synthesis spends a model call on every run (spec 35).
    idempotency = NON_IDEMPOTENT

    async def run(
        self,
        ctx: NodeContext,
        params: RAGParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        llm_cred = ctx.credentials.get("llm")
        if not llm_cred:
            raise NodeExecutionError(
                "The RAG Pipeline node needs an 'llm' credential.",
                code="CREDENTIALS_REQUIRED", node_id="rag_pipeline", retryable=False,
            )

        query = params.query
        if not query and input_items:
            query = str(input_items[0])
        if not query:
            raise NodeExecutionError(
                "No query provided for RAG pipeline.",
                code="MISSING_QUERY", node_id="rag_pipeline", retryable=False,
            )

        try:  # optional AI extras (backend/requirements-ai.txt) - embeddings
            embedding_model = _get_embedding_model(params.embedding_model)
            query_embedding = _embed_list(embedding_model, [query])[0]
        except ImportError:
            raise NodeExecutionError(
                "The RAG Pipeline node needs the optional AI extras: "
                "pip install -r backend/requirements-ai.txt",
                code="OPTIONAL_DEPS_MISSING", node_id="rag_pipeline", retryable=False,
            )

        # --- vector store phase (tenant-scoped since Phase 18) ----------
        try:
            try:
                store, store_name, rec = _resolve_collection(ctx, params.collection_name)
            except VectorStoreUnavailable as e:
                raise _store_unavailable(e) from e
            except ValueError as e:  # unknown backend configured
                raise NodeExecutionError(
                    str(e), code="UNKNOWN_VECTOR_STORE", node_id="rag_pipeline", retryable=False,
                ) from e
            dim = rec.dim if (rec is not None and rec.dim) else len(query_embedding)
            handle = store.ensure_collection(store_name, dim)

            # Ingestion phase — stable doc ids make re-runs idempotent
            # (the same source REPLACES its chunks instead of duplicating).
            if params.source:
                source_text = await _load_source_text(params.source_type, params.source, ctx)
                chunks = _chunk_text(source_text, params.chunk_size, params.chunk_overlap)
                if chunks:
                    import hashlib

                    base = _source_metadata(params.source_type, params.source)
                    doc_id = hashlib.sha256(
                        f"{params.source_type}:{params.source}".encode("utf-8")
                    ).hexdigest()[:24]
                    store.add(
                        handle,
                        documents=chunks,
                        embeddings=_embed_list(embedding_model, chunks),
                        metadatas=[
                            {"chunk_index": i, "source": params.source_type,
                             "document_id": doc_id, **base}
                            for i in range(len(chunks))
                        ],
                        ids=[doc_id] * len(chunks),
                    )

            # Retrieval phase
            hits = store.query(handle, query_embedding, params.top_k)
        except VectorStoreUnavailable as e:
            raise _store_unavailable(e) from e

        retrieved = [
            h for h in hits
            if h.get("similarity", 0.0) >= params.similarity_threshold
        ]

        # --- generation phase (cited context, Phase 18) ------------------
        if not retrieved:
            return NodeResult(output_items=[{"answer": "No relevant context found.", "chunks_used": 0}])

        for ref, hit in enumerate(retrieved, start=1):
            hit["ref"] = ref
        context = "\n\n---\n\n".join(f"[{h['ref']}] {h['content']}" for h in retrieved)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            system_prompt=params.system_prompt,
            context=context,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        try:
            response = await chat_completion(
                credential=llm_cred,
                messages=messages,
                temperature=params.temperature,
                max_tokens=params.max_tokens,
            )
        except LLMError as e:
            raise NodeExecutionError(
                f"LLM error: {e.message}",
                code=e.code, node_id="rag_pipeline", retryable=False,
            )

        answer = response.get("content", "").strip()

        return NodeResult(output_items=[{
            "answer": answer,
            "chunks_used": len(retrieved),
            "citations": [
                {
                    "ref": h["ref"],
                    "similarity": h.get("similarity"),
                    "document_id": (h.get("metadata") or {}).get("document_id"),
                    "source": (h.get("metadata") or {}).get("url")
                    or (h.get("metadata") or {}).get("file_path")
                    or (h.get("metadata") or {}).get("source"),
                    "chunk_index": (h.get("metadata") or {}).get("chunk_index"),
                    "excerpt": str(h.get("content", ""))[:160],
                }
                for h in retrieved
            ],
            "chunks": [
                {"content": r["content"][:200], "similarity": r["similarity"], "metadata": r["metadata"]}
                for r in retrieved
            ],
        }])
