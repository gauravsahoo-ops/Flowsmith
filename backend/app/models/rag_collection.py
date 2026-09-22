"""RAG collection registry (Phase 18: production RAG).

A RagCollection is the tenant-scoped, permission-checked handle for one
knowledge base. The physical vector-store collection name is a random,
opaque key — user-supplied names are NEVER used directly against the
store, so cross-tenant guessing by name is impossible. Every access
goes through app/rag/service.py which enforces:

- workspace collections: visible to workspace members; ingest needs edit
- personal collections (no workspace): owner-only
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

if TYPE_CHECKING:
    pass


class RagCollection(Base):
    __tablename__ = "rag_collections"
    # Named to match migration d7f1a2b3c4e5 (uq_rag_collections_store_name)
    # so create_all and migrated schemas agree on the backing index name.
    __table_args__ = (
        UniqueConstraint("store_name", name="uq_rag_collections_store_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Logical, human-chosen name — unique per tenant scope.
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Opaque physical collection key in the vector store.
    store_name: Mapped[str] = mapped_column(String(80), nullable=False)

    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id"), index=True, nullable=True
    )

    embedding_model: Mapped[str] = mapped_column(String(120), default="all-MiniLM-L6-v2")
    dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
