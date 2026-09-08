"""Vector store abstraction (Phase 14 → pgvector migration): pluggable
backends for the RAG Pipeline node (spec 20).

Contract — a store persists `(documents, embeddings, metadatas)` per
named collection and answers nearest-neighbour queries, returning hits
with a cosine similarity in (-1..1] where 1.0 means identical, so
consumers can threshold without knowing the backend:

    ensure_collection(name, dim) -> handle
    add(handle, documents=[...], embeddings=[[...]], metadatas=[{...}])
    query(handle, query_embedding, top_k) -> [ {content, metadata, similarity} ]
                                    sorted by similarity, best first

Backends (config key `VECTOR_STORE`, default `pgvector`):

- pgvector — PostgreSQL + pgvector extension. Production backend:
  collections live in per-collection tables with cosine HNSW indexes,
  backed up / migrated together with every other table by Alembic and
  pg_dump. See `app/vectorstores/pgvector.py` for the dimension model.

Add your own backend: subclass VectorStore, set `backend_name` and
decorate with `register_store`; selection happens automatically via
`get_vector_store()`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from app.config import get_settings

_StoreT = TypeVar("_StoreT", bound="VectorStore")


class VectorStoreUnavailable(RuntimeError):
    """The configured backend cannot be used (missing optional deps)."""


class VectorStore(ABC):
    """Backend contract. Handles are opaque; treat them as values only."""

    backend_name: str = ""

    @abstractmethod
    def ensure_collection(self, name: str, dim: int) -> Any:
        """Make a named collection exist with the given embedding
        dimension; returns an opaque handle for add()/query()."""

    @abstractmethod
    def add(
        self,
        handle: Any,
        *,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Add chunks with their embeddings and metadata.

        `ids` are stable document identifiers: when given, re-adding an
        existing id REPLACES its chunks (idempotent re-indexing).
        Returns the ids actually stored (generated when omitted)."""

    @abstractmethod
    def query(
        self,
        handle: Any,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Top-k nearest hits, best first, each with
        {content, metadata, similarity} (cosine, 1.0 == identical)."""

    # --- Phase 18 hardening (backends may raise NotImplementedError) ----

    def delete_chunks(self, handle: Any, chunk_ids: list[int]) -> int:
        """Remove specific chunks; returns the number deleted."""
        raise NotImplementedError(f"{self.backend_name} does not support delete_chunks")

    def delete_documents(self, handle: Any, ids: list[str]) -> int:
        """Remove every chunk belonging to the given document ids."""
        raise NotImplementedError(f"{self.backend_name} does not support delete_documents")

    def count(self, handle: Any) -> int:
        """Number of chunks currently stored in the collection."""
        raise NotImplementedError(f"{self.backend_name} does not support count")

    def document_ids(self, handle: Any) -> list[str]:
        """Distinct document ids present in the collection."""
        raise NotImplementedError(f"{self.backend_name} does not support document_ids")

    def list_collections(self) -> list[dict[str, Any]]:
        """[{name, dim, chunks}] for every collection in this store."""
        raise NotImplementedError(f"{self.backend_name} does not support list_collections")

    def delete_collection(self, name: str) -> bool:
        """Drop a whole collection; True when it existed."""
        raise NotImplementedError(f"{self.backend_name} does not support delete_collection")


_STORES: dict[str, type[VectorStore]] = {}


def register_store(cls: type[_StoreT]) -> type[_StoreT]:
    if not cls.backend_name:
        raise ValueError(f"Vector store class {cls.__name__} has no backend_name.")
    _STORES[cls.backend_name] = cls
    return cls


def store_names() -> list[str]:
    return sorted(_STORES)


def get_vector_store() -> VectorStore:
    """Instantiate the configured backend (Settings.vector_store)."""
    name = get_settings().vector_store
    cls = _STORES.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown vector store '{name}' (available: {', '.join(store_names() or ['<none>'])})"
        )
    return cls()


# Importing the backend module registers it (no heavy imports at module
# load: the pgvector store resolves the app engine lazily per call).
from app.vectorstores import pgvector as _pgvector_backend  # noqa: E402,F401