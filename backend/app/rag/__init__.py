"""Production RAG service (Phase 18).

The ONLY sanctioned path to vector collections. Everything the node and
the API do goes through here so that:

- **Tenant isolation** — a collection is a RagCollection row whose
  physical store name is an opaque random key; access checks run on
  every operation (workspace membership / ownership).
- **Idempotent ingestion** — chunks carry stable doc ids; re-ingesting
  the same document replaces it instead of duplicating.
- **Retrieval debugging** — queries return per-phase timings, hit
  counts before/after thresholding, and full scores/metadata.

Embeddings use sentence-transformers (optional AI extra); a deterministic
fallback embedding is available for tests (hash-based, dependency-free).
"""

from __future__ import annotations

import copy
import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RagCollection
from app.vectorstores import VectorStoreUnavailable, get_vector_store

logger = logging.getLogger("rag")

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Module-level cache (the model is expensive to load once per process).
_embedding_model: Any = None


def _get_embedding_model(model_name: str) -> Any:
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]

        _embedding_model = SentenceTransformer(model_name)
    return _embedding_model


def embed_texts(texts: list[str], model_name: str = DEFAULT_EMBEDDING_MODEL) -> list[list[float]]:
    """Real embeddings via sentence-transformers (with automatic dev fallback
    when optional extra is missing in non-production)."""
    try:
        model = _get_embedding_model(model_name)
        vectors = model.encode(texts)
        return [
            [float(x) for x in (v.tolist() if hasattr(v, "tolist") else v)]
            for v in vectors
        ]
    except (ImportError, Exception) as exc:
        import os
        if os.environ.get("APP_ENV") != "production":
            logger.warning("sentence_transformers unavailable (%s); using deterministic dev embeddings", exc)
            return fake_embed_texts(texts, model_name, dim=384)
        raise EmbeddingUnavailable(
            "RAG needs the optional AI extras: pip install -r backend/requirements-ai.txt"
        ) from exc


def fake_embed_texts(
    texts: list[str], model_name: str = DEFAULT_EMBEDDING_MODEL, dim: int = 384,
) -> list[list[float]]:
    """Deterministic hash embeddings — tests and offline demos only.

    Generates stable, unit-normalized vectors using shake_256 hash.
    """
    import os
    if os.environ.get("APP_ENV") == "production":
        raise RuntimeError(
            "fake_embed_texts() must not be called in production. "
            "Use real embeddings (sentence-transformers) instead."
        )
    out: list[list[float]] = []
    for text in texts:
        raw = hashlib.shake_256(f"{model_name}:{text}".encode("utf-8")).digest(dim)
        vec = [(b - 128) / 128.0 for b in raw]
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        out.append([v / norm for v in vec])
    return out


class EmbeddingUnavailable(RuntimeError):
    pass


@dataclass
class RagAccess:
    """Resolved tenant identity for one RAG operation."""

    user_id: int
    workspace_id: str | None = None
    # Workspace ids this user may read/edit, resolved by the caller.
    readable_workspaces: set[str] = field(default_factory=set)
    editable_workspaces: set[str] = field(default_factory=set)


class RagPermissionError(PermissionError):
    def __init__(self, message: str = "You do not have access to this collection.") -> None:
        super().__init__(message)
        self.message = message


def _can_read(rec: RagCollection, access: RagAccess) -> bool:
    if rec.owner_user_id == access.user_id:
        return True
    if rec.workspace_id is None:
        return False  # personal collections are owner-only
    return rec.workspace_id in access.readable_workspaces


def _can_edit(rec: RagCollection, access: RagAccess) -> bool:
    if rec.owner_user_id == access.user_id:
        return True
    if rec.workspace_id is None:
        return False
    return rec.workspace_id in access.editable_workspaces


def _resolve_access(db: Session, access: RagAccess) -> None:
    """Fill workspace sets from membership when the caller did not."""
    from app.models import WorkspaceMember

    if not access.readable_workspaces:
        rows = db.scalars(
            select(WorkspaceMember).where(WorkspaceMember.user_id == access.user_id)
        ).all()
        for m in rows:
            access.readable_workspaces.add(m.workspace_id)
            # Every member can read; role decides edit rights.
            if (m.role or "") in ("owner", "admin", "editor"):
                access.editable_workspaces.add(m.workspace_id)


# ----------------------------------------------------------------------
# collection management
# ----------------------------------------------------------------------

def create_collection(
    db: Session,
    *,
    name: str,
    access: RagAccess,
    description: str = "",
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    metadata: dict[str, Any] | None = None,
) -> RagCollection:
    _resolve_access(db, access)
    if access.workspace_id and access.workspace_id not in access.editable_workspaces:
        raise RagPermissionError("You cannot create collections in this workspace.")
    duplicate = db.scalar(
        select(RagCollection).where(
            RagCollection.name == name,
            RagCollection.owner_user_id == access.user_id,
            RagCollection.workspace_id == access.workspace_id,
        )
    )
    if duplicate is not None:
        raise ValueError(f"A collection named '{name}' already exists.")
    rec = RagCollection(
        id=f"rc_{uuid.uuid4().hex[:12]}",
        name=name,
        store_name=f"rcstore_{uuid.uuid4().hex[:20]}",
        owner_user_id=access.user_id,
        workspace_id=access.workspace_id,
        embedding_model=embedding_model,
        description=description,
        metadata_=metadata,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def list_collections(db: Session, access: RagAccess) -> list[RagCollection]:
    _resolve_access(db, access)
    rows = db.scalars(select(RagCollection)).all()
    return [r for r in rows if _can_read(r, access)]


def get_collection(db: Session, collection_id: str, access: RagAccess) -> RagCollection:
    rec = db.get(RagCollection, collection_id)
    if rec is None:
        raise LookupError("Collection not found.")
    if not _can_read(rec, access):
        raise RagPermissionError()
    return rec


def require_edit(db: Session, collection_id: str, access: RagAccess) -> RagCollection:
    rec = get_collection(db, collection_id, access)
    if not _can_edit(rec, access):
        raise RagPermissionError("Editing this collection requires editor access.")
    return rec


def delete_collection(db: Session, collection_id: str, access: RagAccess) -> dict:
    rec = require_edit(db, collection_id, access)
    store = get_vector_store()
    try:
        existed = store.delete_collection(rec.store_name)
    except VectorStoreUnavailable as exc:
        raise EmbeddingUnavailable(str(exc)) from exc
    db.delete(rec)
    db.commit()
    return {"id": collection_id, "deleted": True, "vectors_dropped": existed}


def collection_stats(db: Session, collection_id: str, access: RagAccess) -> dict:
    rec = get_collection(db, collection_id, access)
    store = get_vector_store()
    try:
        handle = store.ensure_collection(rec.store_name, rec.dim or 1)
        chunks = store.count(handle) if hasattr(store, "count") else None
        docs = store.document_ids(handle) if hasattr(store, "document_ids") else []
    except VectorStoreUnavailable as exc:
        raise EmbeddingUnavailable(str(exc)) from exc
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    return {
        "id": rec.id,
        "name": rec.name,
        "workspace_id": rec.workspace_id,
        "embedding_model": rec.embedding_model,
        "dim": rec.dim,
        "chunks": chunks,
        "documents": docs,
    }


# ----------------------------------------------------------------------
# ingestion / re-indexing / deletion
# ----------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split into overlapping character chunks (shared with the node)."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(end - overlap, 0)
        if start >= len(text):
            break
    return chunks


def ingest_documents(
    db: Session,
    collection_id: str,
    *,
    documents: list[dict[str, Any]],
    access: RagAccess,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    embed_fn=None,
) -> dict[str, Any]:
    """Chunk + embed + upsert documents.

    Each document: {id?, text, metadata?}. Without an explicit id the
    content hash becomes the id, so identical content never duplicates.
    """
    rec = require_edit(db, collection_id, access)
    if not documents:
        raise ValueError("No documents provided.")
    _embed = embed_fn or embed_texts

    t0 = time.perf_counter()
    prepared: list[dict[str, Any]] = []
    for doc in documents:
        text = str(doc.get("text") or "").strip()
        if not text:
            continue
        doc_id = str(doc.get("id") or hashlib.sha256(text.encode("utf-8")).hexdigest()[:24])
        base_meta = {"collection": rec.name, **(doc.get("metadata") or {})}
        for i, piece in enumerate(chunk_text(text, chunk_size, chunk_overlap)):
            prepared.append({
                "doc_id": doc_id,
                "text": piece,
                "metadata": {**base_meta, "chunk_index": i, "document_id": doc_id},
            })
    if not prepared:
        raise ValueError("Documents contained no usable text.")

    try:
        embeddings = _embed([p["text"] for p in prepared], rec.embedding_model)
    except EmbeddingUnavailable:
        raise
    t_embed = time.perf_counter()

    if rec.dim is None:
        rec.dim = len(embeddings[0])
        db.commit()
    elif rec.dim != len(embeddings[0]):
        raise RuntimeError(
            f"Collection '{rec.name}' was built with dim={rec.dim}; "
            f"current embeddings are dim={len(embeddings[0])}."
        )

    store = get_vector_store()
    handle = store.ensure_collection(rec.store_name, rec.dim)
    store.add(
        handle,
        documents=[p["text"] for p in prepared],
        embeddings=embeddings,
        metadatas=[p["metadata"] for p in prepared],
        ids=[p["doc_id"] for p in prepared],
    )
    t_store = time.perf_counter()
    logger.info("ingested %d chunks into %s", len(prepared), rec.id)
    return {
        "chunks_upserted": len(prepared),
        "documents": sorted({p["doc_id"] for p in prepared}),
        "timing_ms": {
            "embed": round((t_embed - t0) * 1000, 1),
            "store": round((t_store - t_embed) * 1000, 1),
        },
    }


def delete_document(
    db: Session, collection_id: str, document_id: str, *, access: RagAccess,
) -> dict:
    rec = require_edit(db, collection_id, access)
    store = get_vector_store()
    handle = store.ensure_collection(rec.store_name, rec.dim or 1)
    removed = store.delete_documents(handle, [document_id])
    return {"document_id": document_id, "chunks_removed": removed}


def reindex_document(
    db: Session,
    collection_id: str,
    document_id: str,
    *,
    text: str,
    metadata: dict[str, Any] | None,
    access: RagAccess,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    embed_fn=None,
) -> dict:
    """Replace one document's chunks atomically (delete + upsert by id)."""
    return ingest_documents(
        db, collection_id,
        documents=[{"id": document_id, "text": text, "metadata": metadata}],
        access=access, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        embed_fn=embed_fn,
    )


# ----------------------------------------------------------------------
# retrieval (+ debugging) & citations
# ----------------------------------------------------------------------

def bm25_sparse_score(query: str, document_text: str) -> float:
    """Compute lightweight BM25-style term frequency score between query and document text."""
    query_tokens = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
    if not query_tokens:
        return 0.0
    doc_tokens = re.findall(r"\w+", document_text.lower())
    doc_len = len(doc_tokens)
    if doc_len == 0:
        return 0.0

    score = 0.0
    for qt in query_tokens:
        tf = doc_tokens.count(qt)
        if tf > 0:
            k1 = 1.2
            b = 0.75
            norm_len = doc_len / 100.0
            score += (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * norm_len))
    return score


def reciprocal_rank_fusion(
    dense_hits: list[dict[str, Any]],
    sparse_scores: dict[str, float],
    k: int = 60,
    dense_weight: float = 0.6,
    sparse_weight: float = 0.4,
) -> list[dict[str, Any]]:
    """Combine dense vector similarity rankings and sparse BM25 scores using Reciprocal Rank Fusion."""
    sorted_sparse = sorted(sparse_scores.items(), key=lambda x: x[1], reverse=True)
    sparse_ranks = {doc_id: rank + 1 for rank, (doc_id, score) in enumerate(sorted_sparse) if score > 0}

    fused_scores: dict[str, float] = {}
    hit_map = {h.get("id") or str(i): h for i, h in enumerate(dense_hits)}

    # Dense RRF contribution
    for rank, h in enumerate(dense_hits, start=1):
        h_id = h.get("id") or str(rank - 1)
        rrf = dense_weight / (k + rank)
        fused_scores[h_id] = fused_scores.get(h_id, 0.0) + rrf

    # Sparse RRF contribution
    for h_id, rank in sparse_ranks.items():
        if h_id in hit_map:
            rrf = sparse_weight / (k + rank)
            fused_scores[h_id] = fused_scores.get(h_id, 0.0) + rrf

    # Re-rank hits by fused score
    re_ranked = []
    for h_id, fused in sorted(fused_scores.items(), key=lambda x: x[1], reverse=True):
        if h_id in hit_map:
            hit = copy.deepcopy(hit_map[h_id])
            hit["rrf_score"] = round(fused, 5)
            hit["sparse_score"] = round(sparse_scores.get(h_id, 0.0), 3)
            hit["hybrid"] = True
            re_ranked.append(hit)

    return re_ranked or dense_hits


def query_collection(
    db: Session,
    collection_id: str,
    *,
    query_text: str,
    top_k: int = 4,
    similarity_threshold: float = 0.3,
    access: RagAccess,
    embed_fn=None,
    hybrid: bool = False,
    dense_weight: float = 0.6,
    sparse_weight: float = 0.4,
) -> dict[str, Any]:
    """Scored retrieval with debugging telemetry; citations-ready hits."""
    rec = get_collection(db, collection_id, access)
    if not query_text.strip():
        raise ValueError("Empty query.")
    _embed = embed_fn or embed_texts

    t0 = time.perf_counter()
    qvec = _embed([query_text], rec.embedding_model)[0]
    if rec.dim is None:
        rec.dim = len(qvec)
        db.commit()
    t_embed = time.perf_counter()

    store = get_vector_store()
    handle = store.ensure_collection(rec.store_name, rec.dim)
    candidate_k = top_k * 2 if hybrid else top_k
    hits = store.query(handle, qvec, candidate_k)
    t_search = time.perf_counter()

    if hybrid and hits:
        sparse_scores = {}
        for i, h in enumerate(hits):
            h_id = h.get("id") or str(i)
            doc_content = str(h.get("content") or "")
            sparse_scores[h_id] = bm25_sparse_score(query_text, doc_content)
        fused = reciprocal_rank_fusion(
            hits, sparse_scores, k=60, dense_weight=dense_weight, sparse_weight=sparse_weight
        )
        kept = [h for h in fused[:top_k] if h.get("similarity", 0.0) >= similarity_threshold or h.get("sparse_score", 0.0) > 0.5]
    else:
        kept = [h for h in hits[:top_k] if h.get("similarity", 0.0) >= similarity_threshold]

    # Citation refs: best hit is [1].
    for ref, hit in enumerate(kept, start=1):
        hit["ref"] = ref
    return {
        "hits": kept,
        "debug": {
            "mode": "hybrid" if hybrid else "dense",
            "total_candidates": len(hits),
            "after_threshold": len(kept),
            "similarity_threshold": similarity_threshold,
            "top_k": top_k,
            "timing_ms": {
                "embed": round((t_embed - t0) * 1000, 1),
                "search": round((t_search - t_embed) * 1000, 1),
                "total": round((time.perf_counter() - t0) * 1000, 1),
            },
        },
    }


def build_cited_context(hits: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Format hits as numbered context blocks for grounded LLM answers."""
    blocks: list[str] = []
    citations: list[dict[str, Any]] = []
    for hit in hits:
        ref = hit.get("ref")
        meta = hit.get("metadata") or {}
        source = meta.get("source_url") or meta.get("source") or meta.get("document_id")
        label = f"[{ref}]" if ref is not None else "[?]"
        blocks.append(f"{label} {hit.get('content', '')}")
        citations.append({
            "ref": ref,
            "similarity": hit.get("similarity"),
            "document_id": meta.get("document_id"),
            "source": source,
            "chunk_index": meta.get("chunk_index"),
            "excerpt": str(hit.get("content", ""))[:160],
        })
    return "\n\n---\n\n".join(blocks), citations
