"""Phase 18 — sqlite_vec hardening: idempotent upserts, deletion,
introspection, atomic alignment.

NOTE: sqlite_vec was retired and replaced by pgvector.
This test file is kept for historical reference but is skipped.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(
    reason="sqlite_vec backend was retired and replaced by pgvector (app.vectorstores.pgvector)"
)

try:
    from app.vectorstores.sqlite_vec import SqliteVecStore
except ImportError:
    SqliteVecStore = None  # type: ignore[assignment,misc]

V1 = [0.1, 0.2, 0.3]
V2 = [0.9, 0.1, 0.1]
QA = [0.1, 0.2, 0.3]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqliteVecStore]:
    s = SqliteVecStore(db_path=str(tmp_path / "vectors.db"))
    yield s
    s.close()


def test_add_returns_ids_and_generates_when_omitted(store: SqliteVecStore):
    handle = store.ensure_collection("docs", 3)
    ids = store.add(handle, documents=["a", "b"], embeddings=[V1, V2],
                    metadatas=[{}, {}], ids=["doc-1", "doc-2"])
    assert ids == ["doc-1", "doc-2"]
    generated = store.add(handle, documents=["c"], embeddings=[V1], metadatas=[{}])
    assert len(generated) == 1 and generated[0].startswith("auto_")


def test_reingest_same_id_replaces_instead_of_duplicating(store: SqliteVecStore):
    handle = store.ensure_collection("docs", 3)
    store.add(handle, documents=["old text"], embeddings=[V1], metadatas=[{}], ids=["doc-1"])
    store.add(handle, documents=["new text"], embeddings=[V2], metadatas=[{}], ids=["doc-1"])
    assert store.count(handle) == 1
    hits = store.query(handle, V2, top_k=5)
    assert hits[0]["content"] == "new text"
    assert hits[0]["similarity"] > 0.99
    assert hits[0]["doc_id"] == "doc-1"


def test_delete_documents_removes_all_chunks_of_a_doc(store: SqliteVecStore):
    handle = store.ensure_collection("docs", 3)
    store.add(handle, documents=["a1", "a2"], embeddings=[V1, V1],
              metadatas=[{}, {}], ids=["doc-a", "doc-a"])
    store.add(handle, documents=["b1"], embeddings=[V2], metadatas=[{}], ids=["doc-b"])
    removed = store.delete_documents(handle, ["doc-a"])
    assert removed == 2
    assert store.count(handle) == 1
    assert store.document_ids(handle) == ["doc-b"]


def test_delete_chunks_by_id(store: SqliteVecStore):
    handle = store.ensure_collection("docs", 3)
    ids = store.add(handle, documents=["x", "y"], embeddings=[V1, V2],
                    metadatas=[{"i": 0}, {"i": 1}], ids=["d", "d"])
    # Both chunks carry the same doc_id but distinct chunk rows; delete one
    # via its query-visible chunk_id.
    hits = store.query(handle, V2, top_k=2)
    target = next(h["chunk_id"] for h in hits if h["content"] == "y")
    assert store.delete_chunks(handle, [target]) == 1
    remaining = store.query(handle, QA, top_k=5)
    assert all(h["content"] != "y" for h in remaining)


def test_list_collections_reports_counts(store: SqliteVecStore):
    h1 = store.ensure_collection("alpha", 3)
    h2 = store.ensure_collection("beta", 3)
    store.add(h1, documents=["x"], embeddings=[V1], metadatas=[{}])
    store.add(h2, documents=["y", "z"], embeddings=[V1, V2], metadatas=[{}, {}])
    listed = {c["name"]: c for c in store.list_collections()}
    assert set(listed) == {"alpha", "beta"}
    assert listed["alpha"]["chunks"] == 1
    assert listed["beta"]["chunks"] == 2
    assert listed["alpha"]["dim"] == 3


def test_delete_collection_drops_everything(store: SqliteVecStore):
    handle = store.ensure_collection("temp", 3)
    store.add(handle, documents=["x"], embeddings=[V1], metadatas=[{}])
    assert store.delete_collection("temp") is True
    assert store.delete_collection("temp") is False
    assert {c["name"] for c in store.list_collections()} == set()
    with pytest.raises(Exception):
        store.count("rcstore_gone")


def test_dim_mismatch_still_guarded(store: SqliteVecStore):
    store.ensure_collection("fixed", 3)
    with pytest.raises(ValueError):
        store.ensure_collection("fixed", 7)
