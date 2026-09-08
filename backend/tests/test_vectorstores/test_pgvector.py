"""pgvector store tests (production backend).

Runs against the real PostgreSQL + pgvector extension. Requires the
test database to be PostgreSQL (conftest creates ``<db>_test``).
"""

from __future__ import annotations

import uuid

import pytest

from app.config import get_settings
from app.vectorstores import store_names
from app.vectorstores.pgvector import PgVectorStore

V1 = [0.1, 0.2, 0.3]
V2 = [0.9, 0.1, 0.1]
V3 = [0.8, 0.8, 0.8]
QA = [0.1, 0.2, 0.3]  # exactly V1 -> similarity ~1.0


@pytest.fixture
def store() -> PgVectorStore:
    s = PgVectorStore()
    yield s


def _uid(prefix: str = "test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# registration / defaults
# ---------------------------------------------------------------------------

def test_backend_is_registered_and_default():
    assert "pgvector" in store_names()
    assert get_settings().vector_store == "pgvector"


def test_get_vector_store_returns_pgvector(monkeypatch):
    from app.vectorstores import get_vector_store

    monkeypatch.setenv("VECTOR_STORE", "pgvector")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        s = get_vector_store()
        assert s.backend_name == "pgvector"
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_unknown_store_raises(monkeypatch):
    from app.vectorstores import get_vector_store

    monkeypatch.setenv("VECTOR_STORE", "does_not_exist")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        with pytest.raises(ValueError, match="Unknown vector store"):
            get_vector_store()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# contract
# ---------------------------------------------------------------------------

def test_add_and_query_best_first(store: PgVectorStore):
    name = _uid("contract")
    handle = store.ensure_collection(name, 3)
    try:
        store.add(
            handle,
            documents=["a", "b", "c"],
            embeddings=[V1, V2, V3],
            metadatas=[{"i": 0}, {"i": 1}, {"i": 2}],
        )
        hits = store.query(handle, QA, top_k=3)
        assert len(hits) == 3
        assert hits[0]["content"] == "a"
        assert hits[0]["similarity"] == pytest.approx(1.0)
        assert [h["content"] for h in hits] == ["a", "c", "b"]
        assert hits[1]["similarity"] > hits[2]["similarity"]
        assert hits[1]["metadata"] == {"i": 2}
    finally:
        store.delete_collection(name)


def test_query_respects_top_k(store: PgVectorStore):
    name = _uid("topk")
    handle = store.ensure_collection(name, 3)
    try:
        store.add(handle, documents=["a", "b", "c"], embeddings=[V1, V2, V3], metadatas=[{}, {}, {}])
        hits = store.query(handle, QA, top_k=1)
        assert len(hits) == 1 and hits[0]["content"] == "a"
    finally:
        store.delete_collection(name)


def test_empty_collection_returns_empty(store: PgVectorStore):
    name = _uid("empty")
    handle = store.ensure_collection(name, 3)
    try:
        assert store.query(handle, QA, top_k=5) == []
        assert store.count(handle) == 0
    finally:
        store.delete_collection(name)


def test_collections_are_isolated(store: PgVectorStore):
    a = _uid("iso_a")
    b = _uid("iso_b")
    ha = store.ensure_collection(a, 3)
    hb = store.ensure_collection(b, 3)
    try:
        store.add(ha, documents=["a"], embeddings=[V1], metadatas=[{}])
        store.add(hb, documents=["b"], embeddings=[V1], metadatas=[{}])
        assert store.query(ha, QA, top_k=5)[0]["content"] == "a"
        assert store.query(hb, QA, top_k=5)[0]["content"] == "b"
        assert store.count(ha) == 1 and store.count(hb) == 1
    finally:
        store.delete_collection(a)
        store.delete_collection(b)


def test_persistence_across_instances():
    # Two independent store objects against the same DB share data.
    name = _uid("persist")
    first = PgVectorStore()
    second = PgVectorStore()
    h1 = first.ensure_collection(name, 3)
    try:
        first.add(h1, documents=["hello"], embeddings=[V1], metadatas=[{}], ids=["doc1"])
        h2 = second.ensure_collection(name, 3)
        hits = second.query(h2, QA, top_k=5)
        assert hits and hits[0]["content"] == "hello"
    finally:
        first.delete_collection(name)


def test_dimension_mismatch_rejected(store: PgVectorStore):
    name = _uid("dim")
    handle = store.ensure_collection(name, 3)
    try:
        with pytest.raises(ValueError, match="already exists with embedding dimension"):
            store.ensure_collection(name, 5)
    finally:
        store.delete_collection(name)


def test_unbalanced_add_rejected(store: PgVectorStore):
    name = _uid("unbalanced")
    handle = store.ensure_collection(name, 3)
    try:
        with pytest.raises(ValueError):
            store.add(handle, documents=["a", "b"], embeddings=[V1], metadatas=[{}, {}])
    finally:
        store.delete_collection(name)


# ---------------------------------------------------------------------------
# hardening (Phase 18 parity)
# ---------------------------------------------------------------------------

def test_add_returns_ids_and_generates_when_omitted(store: PgVectorStore):
    name = _uid("ids")
    handle = store.ensure_collection(name, 3)
    try:
        ids = store.add(handle, documents=["a", "b"], embeddings=[V1, V2], metadatas=[{}, {}], ids=["doc-1", "doc-2"])
        assert ids == ["doc-1", "doc-2"]
        generated = store.add(handle, documents=["c"], embeddings=[V1], metadatas=[{}])
        assert len(generated) == 1 and generated[0].startswith("auto_")
    finally:
        store.delete_collection(name)


def test_reingest_same_id_replaces_instead_of_duplicating(store: PgVectorStore):
    name = _uid("replace")
    handle = store.ensure_collection(name, 3)
    try:
        store.add(handle, documents=["old text"], embeddings=[V1], metadatas=[{}], ids=["doc-1"])
        store.add(handle, documents=["new text"], embeddings=[V2], metadatas=[{}], ids=["doc-1"])
        assert store.count(handle) == 1
        hits = store.query(handle, V2, top_k=5)
        assert hits[0]["content"] == "new text"
        assert hits[0]["similarity"] > 0.99
        assert hits[0]["doc_id"] == "doc-1"
    finally:
        store.delete_collection(name)


def test_delete_documents_removes_all_chunks_of_a_doc(store: PgVectorStore):
    name = _uid("deldoc")
    handle = store.ensure_collection(name, 3)
    try:
        store.add(handle, documents=["a", "a2"], embeddings=[V1, V1], metadatas=[{}, {}], ids=["doc-1", "doc-1"])
        store.add(handle, documents=["b"], embeddings=[V2], metadatas=[{}], ids=["doc-2"])
        assert store.count(handle) == 3  # doc-1 has 2 chunks after dedupe? Actually add with same id replaces, so first add 2 chunks same id -> 2 chunks, second add 1
        removed = store.delete_documents(handle, ["doc-1"])
        assert removed == 2
        assert store.count(handle) == 1
    finally:
        store.delete_collection(name)


def test_delete_chunks_by_id(store: PgVectorStore):
    name = _uid("delchunk")
    handle = store.ensure_collection(name, 3)
    try:
        store.add(handle, documents=["a", "b", "c"], embeddings=[V1, V2, V3], metadatas=[{}, {}, {}])
        hits = store.query(handle, V1, top_k=5)
        # collect one chunk_id to delete
        to_delete = [hits[1]["chunk_id"]]
        assert store.delete_chunks(handle, to_delete) == 1
        assert store.count(handle) == 2
    finally:
        store.delete_collection(name)


def test_list_collections_reports_counts(store: PgVectorStore):
    a = _uid("list_a")
    b = _uid("list_b")
    ha = store.ensure_collection(a, 3)
    hb = store.ensure_collection(b, 3)
    try:
        store.add(ha, documents=["x"], embeddings=[V1], metadatas=[{}])
        listing = {c["name"]: c for c in store.list_collections()}
        assert a in listing and b in listing
        assert listing[a]["chunks"] == 1
        assert listing[b]["chunks"] == 0
    finally:
        store.delete_collection(a)
        store.delete_collection(b)


def test_delete_collection_drops_everything(store: PgVectorStore):
    name = _uid("drop")
    handle = store.ensure_collection(name, 3)
    store.add(handle, documents=["a"], embeddings=[V1], metadatas=[{}])
    assert store.delete_collection(name) is True
    assert store.delete_collection(name) is False
    # Re-creating same name with different dim should now succeed (no mismatch).
    handle2 = store.ensure_collection(name, 5)
    try:
        assert handle2  # new table created with dim 5
    finally:
        store.delete_collection(name)
