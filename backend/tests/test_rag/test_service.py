"""Phase 18 — RAG service: tenant isolation, permissions, ingestion
idempotency, retrieval debugging, citations.

Runs against the test database with deterministic hash embeddings (no
optional AI extras needed).
"""

from __future__ import annotations

import pytest

from app.models import RagCollection, WorkspaceMember
from app.rag import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingUnavailable,
    RagAccess,
    RagPermissionError,
    build_cited_context,
    chunk_text,
    collection_stats,
    create_collection,
    delete_collection,
    delete_document,
    get_collection,
    ingest_documents,
    list_collections,
    query_collection,
)
from app.db import get_session


@pytest.fixture
def db():
    session = get_session()
    yield session
    session.close()


@pytest.fixture
def users(db) -> dict:
    from app.models import User

    def mk(email: str) -> User:
        u = User(email=email, password_hash="x")
        db.add(u)
        db.commit()
        return u

    alice = mk("alice@rag.test")
    bob = mk("bob@rag.test")
    return {"alice": alice, "bob": bob}


def _access(user: User, workspace_id: str | None = None,
            readable: set[str] | None = None, editable: set[str] | None = None) -> RagAccess:
    return RagAccess(
        user_id=user.id, workspace_id=workspace_id,
        readable_workspaces=readable or set(),
        editable_workspaces=editable or set(),
    )


def _fake_embed(texts, model=DEFAULT_EMBEDDING_MODEL):
    from app.rag import fake_embed_texts

    return fake_embed_texts(texts, model)


# ----------------------------------------------------------------------
# isolation basics
# ----------------------------------------------------------------------

def test_personal_collections_are_owner_only(db, users):
    rec = create_collection(db, name="private", access=_access(users["alice"]))
    # Bob cannot even see it.
    assert all(r.id != rec.id for r in list_collections(db, _access(users["bob"])))
    with pytest.raises(RagPermissionError):
        get_collection(db, rec.id, _access(users["bob"]))


def test_opaque_store_names_never_leak_user_input(db, users):
    rec = create_collection(db, name="kb", access=_access(users["alice"]))
    assert rec.store_name.startswith("rcstore_")
    assert "kb" not in rec.store_name


def test_duplicate_names_rejected_within_scope(db, users):
    create_collection(db, name="dup", access=_access(users["alice"]))
    with pytest.raises(ValueError):
        create_collection(db, name="dup", access=_access(users["alice"]))


# ----------------------------------------------------------------------
# workspace scoping
# ----------------------------------------------------------------------

def test_workspace_member_roles_drive_access(db, users):
    from app.models import Organization, Workspace

    org = Organization(id="org_rag", name="rag-org", founder_id=users["alice"].id)
    db.add(org)
    ws = Workspace(id="ws_rag", name="RagWs", organization_id="org_rag",
                   creator_id=users["alice"].id)
    db.add(ws)
    db.add(WorkspaceMember(workspace_id="ws_rag", user_id=users["alice"].id,
                           role="owner", permission="edit"))
    db.add(WorkspaceMember(workspace_id="ws_rag", user_id=users["bob"].id,
                           role="viewer", permission="view"))
    db.commit()

    rec = create_collection(
        db, name="team-kb",
        access=_access(users["alice"], workspace_id="ws_rag",
                       editable={"ws_rag"}, readable={"ws_rag"}),
    )
    assert rec.workspace_id == "ws_rag"

    # Viewer (read-only member) can read but not edit.
    viewer = RagAccess(user_id=users["bob"].id, readable_workspaces={"ws_rag"})
    assert get_collection(db, rec.id, viewer).id == rec.id
    with pytest.raises(RagPermissionError):
        ingest_documents(db, rec.id, documents=[{"text": "x"}], access=viewer,
                         embed_fn=_fake_embed)

    # Outsider sees nothing.
    outsider = RagAccess(user_id=99999)
    with pytest.raises(RagPermissionError):
        get_collection(db, rec.id, outsider)


# ----------------------------------------------------------------------
# ingestion / reindex / delete
# ----------------------------------------------------------------------

def _mk_and_fill(db, users, name="filled") -> RagCollection:
    rec = create_collection(db, name=name, access=_access(users["alice"]))
    ingest_documents(db, rec.id, embed_fn=_fake_embed, access=_access(users["alice"]),
                     documents=[
        {"id": "doc-1", "text": "alpha beta gamma"},
        {"id": "doc-2", "text": "delta epsilon zeta"},
    ])
    return rec


def test_ingest_is_idempotent_by_doc_id(db, users):
    rec = _mk_and_fill(users and db, users)
    stats = collection_stats(db, rec.id, _access(users["alice"]))
    before = stats["chunks"]
    # Re-ingest doc-1 with new content: replaced, not appended.
    ingest_documents(db, rec.id, embed_fn=_fake_embed,
                     access=_access(users["alice"]),
                     documents=[{"id": "doc-1", "text": "totally different"}])
    after = collection_stats(db, rec.id, _access(users["alice"]))
    assert after["chunks"] == before  # 1:1 replacement
    hits = query_collection(db, rec.id, query_text="totally different",
                            access=_access(users["alice"]), embed_fn=_fake_embed)["hits"]
    assert hits and hits[0]["doc_id"] == "doc-1"


def test_content_hash_ids_prevent_accidental_duplication(db, users):
    rec = create_collection(db, name="hashes", access=_access(users["alice"]))
    payload = [{"text": "same content"}]
    ingest_documents(db, rec.id, embed_fn=_fake_embed, access=_access(users["alice"]), documents=payload)
    ingest_documents(db, rec.id, embed_fn=_fake_embed, access=_access(users["alice"]), documents=payload)
    stats = collection_stats(db, rec.id, _access(users["alice"]))
    assert stats["chunks"] == 1  # same text -> same hash id -> upsert


def test_delete_document(db, users):
    rec = _mk_and_fill(db, users, name="delme")
    result = delete_document(db, rec.id, "doc-1", access=_access(users["alice"]))
    assert result["chunks_removed"] >= 1
    remaining = collection_stats(db, rec.id, _access(users["alice"]))["documents"]
    assert remaining == ["doc-2"]


def test_reindex_replaces_atomically(db, users):
    rec = _mk_and_fill(db, users, name="reidx")
    reindexed = None
    from app.rag import reindex_document

    reindexed = reindex_document(
        db, rec.id, "doc-2", text="brand new content for doc two",
        metadata={"rev": 2}, access=_access(users["alice"]), embed_fn=_fake_embed,
    )
    assert reindexed["chunks_upserted"] >= 1
    docs = collection_stats(db, rec.id, _access(users["alice"]))["documents"]
    assert sorted(docs) == ["doc-1", "doc-2"]


def test_delete_collection_removes_registry_and_vectors(db, users):
    rec = _mk_and_fill(db, users, name="gone")
    result = delete_collection(db, rec.id, access=_access(users["alice"]))
    assert result["deleted"] is True
    db.expire_all()
    assert db.get(RagCollection, rec.id) is None


def test_query_debug_telemetry_and_threshold_funnel(db, users):
    rec = _mk_and_fill(db, users, name="dbg")
    out = query_collection(
        db, rec.id, query_text="delta", top_k=4, similarity_threshold=0.95,
        access=_access(users["alice"]), embed_fn=_fake_embed,
    )
    debug = out["debug"]
    assert debug["total_candidates"] >= 0
    assert {"embed", "search", "total"} <= set(debug["timing_ms"])
    assert debug["similarity_threshold"] == 0.95


# ----------------------------------------------------------------------
# citations
# ----------------------------------------------------------------------

def test_build_cited_context_numbers_best_first():
    hits = [
        {"ref": 1, "content": "first block", "similarity": 0.9,
         "metadata": {"document_id": "d1", "chunk_index": 0}},
        {"ref": 2, "content": "second block", "similarity": 0.8,
         "metadata": {"document_id": "d2"}},
    ]
    context, citations = build_cited_context(hits)
    assert context.startswith("[1] first block")
    assert "[2] second block" in context
    assert [c["ref"] for c in citations] == [1, 2]
    assert citations[0]["document_id"] == "d1"


def test_chunk_text_overlap_bounds():
    chunks = chunk_text("x" * 1200, chunk_size=500, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c) <= 500 for c in chunks)
    assert chunk_text("   ", 500, 50) == []


def test_empty_ingest_rejected(db, users):
    rec = create_collection(db, name="empty", access=_access(users["alice"]))
    with pytest.raises(ValueError):
        ingest_documents(db, rec.id, embed_fn=_fake_embed,
                         access=_access(users["alice"]),
                         documents=[{"text": "   "}])
