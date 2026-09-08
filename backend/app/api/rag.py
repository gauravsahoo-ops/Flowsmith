"""RAG collections API (Phase 18: production RAG).

Tenant-scoped knowledge-base management over the vector store:

- CRUD for collections (workspace-scoped or personal)
- document ingestion / re-indexing / deletion (idempotent by doc id)
- scored retrieval with debugging telemetry and citation-ready hits

Every operation goes through app/rag/service.py, which enforces
membership/ownership. Embeddings need the optional AI extras; the
endpoints answer 503 with install instructions when they are missing.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok
from app.audit import AI_ASSIST, log_event
from app.db import get_db
from app.models import User
from app.rag import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingUnavailable,
    RagAccess,
    RagPermissionError,
    collection_stats,
    create_collection,
    delete_collection,
    delete_document,
    get_collection,
    ingest_documents,
    list_collections,
    query_collection,
    reindex_document,
)

router = APIRouter(prefix="/api/rag", tags=["rag"])


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    workspace_id: str | None = None
    description: str = ""
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    metadata: dict[str, Any] | None = None


class DocumentIn(BaseModel):
    id: str | None = None
    text: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    documents: list[DocumentIn] = Field(min_length=1)
    chunk_size: int = Field(default=500, ge=100, le=4000)
    chunk_overlap: int = Field(default=50, ge=0, le=1000)


class ReindexRequest(BaseModel):
    text: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None
    chunk_size: int = Field(default=500, ge=100, le=4000)
    chunk_overlap: int = Field(default=50, ge=0, le=1000)


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=4, ge=1, le=50)
    similarity_threshold: float = Field(default=0.3, ge=-1.0, le=1.0)


def _access(user: User, workspace_id: str | None) -> RagAccess:
    return RagAccess(user_id=user.id, workspace_id=workspace_id)


def _permission_error(exc: RagPermissionError) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, exc.message)


def _unavailable(exc: EmbeddingUnavailable) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


def _to_dict(rec) -> dict:
    return {
        "id": rec.id,
        "name": rec.name,
        "description": rec.description,
        "workspace_id": rec.workspace_id,
        "embedding_model": rec.embedding_model,
        "dim": rec.dim,
        "metadata": rec.metadata_,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


@router.get("/collections")
def get_collections(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = list_collections(db, _access(user, None))
    return ok([_to_dict(r) for r in rows])


@router.post("/collections", status_code=status.HTTP_201_CREATED)
def post_collection(
    body: CollectionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if body.workspace_id:
        from app.api.workspaces import _require_ws_member

        _require_ws_member(db, body.workspace_id, user)
    try:
        rec = create_collection(
            db,
            name=body.name.strip(),
            access=_access(user, body.workspace_id),
            description=body.description,
            embedding_model=body.embedding_model,
            metadata=body.metadata,
        )
    except RagPermissionError as exc:
        raise _permission_error(exc)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    log_event(db, AI_ASSIST, target_type="rag_collection", target_id=rec.id,
              user_id=user.id, detail={"action": "create", "name": rec.name})
    return ok(_to_dict(rec))


@router.get("/collections/{collection_id}")
def get_one(
    collection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return ok(_to_dict(get_collection(db, collection_id, _access(user, None))))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except RagPermissionError as exc:
        # Do not leak existence across tenants.
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)


@router.get("/collections/{collection_id}/stats")
def get_stats(
    collection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return ok(collection_stats(db, collection_id, _access(user, None)))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except RagPermissionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    except EmbeddingUnavailable as exc:
        raise _unavailable(exc)


@router.delete("/collections/{collection_id}")
def delete_one(
    collection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = delete_collection(db, collection_id, _access(user, None))
    except RagPermissionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    except EmbeddingUnavailable as exc:
        raise _unavailable(exc)
    log_event(db, AI_ASSIST, target_type="rag_collection", target_id=collection_id,
              user_id=user.id, detail={"action": "delete"})
    return ok(result)


@router.post("/collections/{collection_id}/documents")
async def post_documents(
    collection_id: str,
    body: IngestRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Ingest documents (idempotent by doc id: same id/content replaces)."""
    try:
        result = ingest_documents(
            db, collection_id,
            documents=[d.model_dump() for d in body.documents],
            access=_access(user, None),
            chunk_size=body.chunk_size,
            chunk_overlap=body.chunk_overlap,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except RagPermissionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except EmbeddingUnavailable as exc:
        raise _unavailable(exc)
    log_event(db, AI_ASSIST, target_type="rag_collection", target_id=collection_id,
              user_id=user.id, detail={"action": "ingest",
                                       "chunks": result["chunks_upserted"]})
    return ok(result)


@router.post("/collections/{collection_id}/documents/{document_id}/reindex")
async def post_reindex(
    collection_id: str,
    document_id: str,
    body: ReindexRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Replace one document's chunks atomically (idempotent upsert)."""
    try:
        result = reindex_document(
            db, collection_id, document_id,
            text=body.text,
            metadata=body.metadata,
            access=_access(user, None),
            chunk_size=body.chunk_size,
            chunk_overlap=body.chunk_overlap,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except RagPermissionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except EmbeddingUnavailable as exc:
        raise _unavailable(exc)
    log_event(db, AI_ASSIST, target_type="rag_collection", target_id=collection_id,
              user_id=user.id, detail={"action": "reindex", "document_id": document_id})
    return ok(result)


@router.delete("/collections/{collection_id}/documents/{document_id}")
def remove_document(
    collection_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return ok(delete_document(db, collection_id, document_id,
                                  access=_access(user, None)))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except RagPermissionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    except EmbeddingUnavailable as exc:
        raise _unavailable(exc)


@router.post("/collections/{collection_id}/query")
async def post_query(
    collection_id: str,
    body: RagQueryRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Scored retrieval with debugging telemetry (timings, threshold
    funnel) and citation-ready refs."""
    try:
        result = query_collection(
            db, collection_id,
            query_text=body.query,
            top_k=body.top_k,
            similarity_threshold=body.similarity_threshold,
            access=_access(user, None),
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except RagPermissionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except EmbeddingUnavailable as exc:
        raise _unavailable(exc)
    return ok(result)
