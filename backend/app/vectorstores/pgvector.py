"""PostgreSQL + pgvector vector store backend (production).

Replaces the former embedded backends (sqlite_vec / chroma). Vectors live
in PostgreSQL next to every other source of truth:

- One catalog table ``vector_collections`` (created by Alembic) tracks
  collection -> physical table + dimension.
- Each collection maps to a per-collection table ``pgvec_<suffix>`` with
  an ``embedding vector(<dim>)`` column typed for THAT collection's
  embedding model. This keeps multi-model support open: a future model
  with different dimensions simply gets a table typed for its own dim
  (a single fixed-width column platform-wide would freeze the choice).
- The physical suffix is derived from the collection's registry name
  (already an opaque random key for tenant-scoped collections), never
  from user-supplied text.
- Similarity = cosine, matching the VectorStore contract:
  ``1 - (embedding <=> query)``, best first, 1.0 == identical.
- Writes are transactional and idempotent per stable doc id: re-adding
  an existing doc id REPLACES its chunks (delete + insert atomically),
  exactly like the previous backends.

Note on tables: per-collection tables are runtime-managed by this module
(like the previous sqlite-vec virtual tables were runtime-managed by its
module); Alembic owns shared/global schema only. Dynamic DDL here uses a
hex-suffixed identifier derived internally — never user input.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import uuid
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.vectorstores import VectorStore, register_store

logger = logging.getLogger("vectorstores.pgvector")

CATALOG_TABLE = "vector_collections"
TABLE_PREFIX = "pgvec_"

_IDENTIFIER_RE = None  # lazy import to avoid circular


def _validate_identifier(name: str, label: str = "identifier") -> str:
    """Reject SQL identifiers that aren't strictly alphanumeric/underscore.

    This is a defence-in-depth guard: all callers already derive table names
    from SHA-256 hashes, but this prevents regressions if future code passes
    user-supplied text.
    """
    import re as _re
    if not name or not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Invalid {label}: {name!r}")
    return name


def _safe_table(name: str) -> str:
    """Return a validated, safe table name for SQL interpolation."""
    _validate_identifier(name, "table name")
    return name


# Pre-validate the constant catalog table name at import time
_validate_identifier(CATALOG_TABLE, "catalog table")
_validate_identifier(TABLE_PREFIX.rstrip("_"), "table prefix")

_ENSURE_CATALOG_SQL = text(
    f"CREATE TABLE IF NOT EXISTS {CATALOG_TABLE} ("
    " name TEXT PRIMARY KEY,"
    " suffix TEXT NOT NULL UNIQUE,"
    " dim INTEGER NOT NULL,"
    " created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)


def _table_suffix(name: str) -> str:
    """Stable, identifier-safe table suffix derived from the collection name."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]


def _table_name(suffix: str) -> str:
    return f"{TABLE_PREFIX}{suffix}"


def _vec_literal(vector: list[float]) -> str:
    """Serialize an embedding to pgvector's text format ('[1,2,3]')."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _jsonb(value: dict[str, Any]) -> Any:
    """Wrap a metadata dict for JSONB binding through psycopg2."""
    import psycopg2.extras

    return psycopg2.extras.Json(value)


@register_store
class PgVectorStore(VectorStore):
    backend_name = "pgvector"

    # --- plumbing ---------------------------------------------------------

    def _connect(self):
        """A connection from the CURRENT app engine (tests may have
        re-pointed it via init_db after import time)."""
        from app.db import engine

        return engine.connect()

    def _ensure_extension(self, conn) -> None:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # --- VectorStore ------------------------------------------------------

    def ensure_collection(self, name: str, dim: int) -> str:
        conn = self._connect()
        try:
            self._ensure_extension(conn)
            conn.execute(_ENSURE_CATALOG_SQL)
            row = conn.execute(
                text(f"SELECT dim FROM {CATALOG_TABLE} WHERE name = :name"),
                {"name": name},
            ).fetchone()
            if row is not None and int(row[0]) != dim:
                raise ValueError(
                    f"Collection '{name}' already exists with embedding dimension "
                    f"{row[0]}; current model produces {dim}."
                )
            if row is None:
                conn.execute(
                    text(f"INSERT INTO {CATALOG_TABLE} (name, suffix, dim) VALUES (:n, :s, :d)"),
                    {"n": name, "s": "", "d": dim},
                )
            suffix = _table_suffix(name)
            table = _table_name(suffix)
            conn.execute(text(f'UPDATE {CATALOG_TABLE} SET suffix = :s WHERE name = :n'),
                         {"s": suffix, "n": name})
            exists = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
                {"t": table},
            ).fetchone()
            if exists is None:
                conn.execute(text(
                    f'CREATE TABLE "{table}" ('
                    " chunk_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,"
                    " doc_id TEXT NOT NULL DEFAULT '',"
                    " document TEXT NOT NULL,"
                    " metadata JSONB NOT NULL DEFAULT '{}'::jsonb,"
                    " embedding vector(:dim) NOT NULL,"
                    " created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                    ")"
                ), {"dim": dim})
            # Cosine-space ANN index (operator class must match <=> usage).
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS "idx_{table}_emb" '
                f'ON "{table}" USING hnsw (embedding vector_cosine_ops)'
            ))
            conn.execute(text(f'CREATE INDEX IF NOT EXISTS "idx_{table}_doc" ON "{table}"(doc_id)'))
            conn.commit()
            return suffix
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add(
        self,
        handle: str,
        *,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        if not documents:
            return []
        if not (len(documents) == len(embeddings) == len(metadatas)):
            raise ValueError("documents/embeddings/metadatas must have equal length")
        if ids is not None and len(ids) != len(documents):
            raise ValueError("ids must match documents length when given")
        table = _table_name(handle)
        conn = self._connect()
        trans = None
        try:
            trans = conn.begin()
            next_seq_row = conn.execute(
                text(f'SELECT COALESCE(MAX(chunk_id), 0) FROM "{table}"')
            ).scalar_one()
            next_seq = int(next_seq_row)
            # Resolve ids: provided non-empty id wins; otherwise a stable
            # synthetic id (`auto_<collection>_<seq>`) is minted here so
            # delete/replace semantics apply uniformly.
            doc_ids: list[str] = []
            for i in range(len(documents)):
                given = ids[i] if ids is not None else None
                doc_ids.append(given if given else f"auto_{handle}_{next_seq + i + 1}")
            unique_ids = list(dict.fromkeys(doc_ids))
            if unique_ids:
                conn.execute(
                    text(f'DELETE FROM "{table}" WHERE doc_id = ANY(:doc_ids)'),
                    {"doc_ids": unique_ids},
                )
            insert_sql = text(
                f'INSERT INTO "{table}" (doc_id, document, metadata, embedding) '
                "VALUES (:doc_id, :document, :metadata, CAST(:embedding AS vector))"
            )
            params = [
                {
                    "doc_id": doc_ids[i],
                    "document": documents[i],
                    "metadata": _jsonb(metadatas[i]),
                    "embedding": _vec_literal(embeddings[i]),
                }
                for i in range(len(documents))
            ]
            conn.execute(insert_sql, params)
            trans.commit()
            return doc_ids
        except Exception:
            if trans is not None:
                trans.rollback()
            raise
        finally:
            conn.close()

    def query(
        self,
        handle: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        table = _table_name(handle)
        conn = self._connect()
        try:
            rows = conn.execute(
                text(
                    f'SELECT chunk_id, document, metadata::text, doc_id, '
                    f'1 - (embedding <=> CAST(:qv AS vector)) AS similarity '
                    f'FROM "{table}" '
                    f"ORDER BY embedding <=> CAST(:qv AS vector) LIMIT :k"
                ),
                {"qv": _vec_literal(query_embedding), "k": top_k},
            ).all()
        finally:
            conn.close()
        hits: list[dict[str, Any]] = []
        for chunk_id, document, metadata_text, doc_id, similarity in rows:
            sim = float(similarity)
            if math.isnan(sim):  # zero-vector cosine edge: treat as no signal
                sim = 0.0
            hits.append({
                "content": document,
                "metadata": json.loads(metadata_text) if metadata_text else {},
                "similarity": round(sim, 6),
                "chunk_id": int(chunk_id),
                "doc_id": doc_id,
            })
        return hits

    # --- hardening surface --------------------------------------------------

    def delete_chunks(self, handle: str, chunk_ids: list[int]) -> int:
        if not chunk_ids:
            return 0
        table = _table_name(handle)
        conn = self._connect()
        try:
            res = conn.execute(
                text(f'DELETE FROM "{table}" WHERE chunk_id = ANY(:ids)'),
                {"ids": list(chunk_ids)},
            )
            conn.commit()
            return res.rowcount or 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_documents(self, handle: str, ids: list[str]) -> int:
        if not ids:
            return 0
        table = _table_name(handle)
        conn = self._connect()
        try:
            res = conn.execute(
                text(f'DELETE FROM "{table}" WHERE doc_id = ANY(:ids)'),
                {"ids": list(ids)},
            )
            conn.commit()
            return res.rowcount or 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def count(self, handle: str) -> int:
        table = _table_name(handle)
        conn = self._connect()
        try:
            return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one())
        finally:
            conn.close()

    def document_ids(self, handle: str) -> list[str]:
        table = _table_name(handle)
        conn = self._connect()
        try:
            rows = conn.execute(
                text(f'SELECT DISTINCT doc_id FROM "{table}" ORDER BY doc_id')
            ).all()
            return [str(r[0]) for r in rows]
        finally:
            conn.close()

    def list_collections(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            self._ensure_extension(conn)
            conn.execute(_ENSURE_CATALOG_SQL)
            out: list[dict[str, Any]] = []
            for name, suffix, dim in conn.execute(
                text(f"SELECT name, suffix, dim FROM {CATALOG_TABLE} ORDER BY name")
            ).all():
                table = _table_name(str(suffix))
                try:
                    chunks = int(conn.execute(
                        text(f'SELECT COUNT(*) FROM "{table}"')
                    ).scalar_one())
                except Exception:
                    chunks = 0
                    conn.rollback()
                out.append({"name": name, "dim": int(dim), "chunks": chunks})
            return out
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_collection(self, name: str) -> bool:
        suffix = _table_suffix(name)
        table = _table_name(suffix)
        conn = self._connect()
        try:
            self._ensure_extension(conn)
            conn.execute(_ENSURE_CATALOG_SQL)
            deleted = bool(conn.execute(
                text(f"DELETE FROM {CATALOG_TABLE} WHERE name = :name RETURNING name"),
                {"name": name},
            ).first())
            conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def migrate_legacy_sqlite_vec(sqlite_path: str) -> dict[str, Any]:
    """One-shot importer from a legacy sqlite-vec ``vectors.db`` file.

    Copies every catalogued collection into pgvector PRESERVING logical
    collection names, dimensions, documents, embeddings and metadata.
    Stable doc ids are preserved when present; auto-generated ids are
    re-generated by add(). The source file is NEVER modified or deleted,
    and imports are idempotent thanks to doc-id replace semantics.

    Returns a report dict; failures are raised, never swallowed.
    """
    import sqlite3

    src = sqlite3.connect(sqlite_path)
    try:
        catalog = src.execute(
            "SELECT name, suffix, dim FROM collections ORDER BY name"
        ).fetchall()
    finally:
        src.close()

    report: dict[str, Any] = {"file": sqlite_path, "collections": []}
    for name, suffix, dim in catalog:
        con = sqlite3.connect(sqlite_path)
        try:
            rows = con.execute(
                f'SELECT v.chunk_id, m.document, m.metadata, m.doc_id '  # noqa: S608
                f'FROM "vec_{suffix}" v JOIN "meta_{suffix}" m ON m.chunk_id = v.chunk_id '
                f'ORDER BY v.chunk_id'
            ).fetchall()
        finally:
            con.close()
        store = PgVectorStore()
        handle = store.ensure_collection(str(name), int(dim))
        chunks = [str(r[1]) for r in rows]
        embeddings = [
            _read_sqlite_embedding(sqlite_path, str(suffix), int(r[0])) for r in rows
        ]
        metadatas = [json.loads(r[2]) if isinstance(r[2], str) else (r[2] or {}) for r in rows]
        ids = [r[3] if r[3] else None for r in rows]
        stored = store.add(
            handle,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=[i for i in ids if i is not None],
        )
        report["collections"].append({
            "name": str(name),
            "dim": int(dim),
            "chunks": len(rows),
            "stored_ids": len(stored),
        })
    return report


def _read_sqlite_embedding(sqlite_path: str, suffix: str, chunk_id: int) -> list[float]:
    """Read one row's embedding from a sqlite-vec vec0 virtual table."""
    con = sqlite3.connect(sqlite_path)
    try:
        row = con.execute(
            f'SELECT embedding FROM "vec_{suffix}" WHERE chunk_id = ?', (chunk_id,)
        ).fetchone()
        raw = row[0]
        if isinstance(raw, bytes):
            # float32 little-endian serialization of the vec0 table.
            import struct

            floats = struct.unpack(f"<{len(raw) // 4}f", raw)
            return [float(x) for x in floats]
        return [float(x) for x in json.loads(raw)]
    finally:
        con.close()
