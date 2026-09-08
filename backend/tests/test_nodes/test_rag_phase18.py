"""Phase 18 — rag_pipeline node hardening: tenant-scoped collections,
idempotent re-ingestion during runs, cited answers.

Uses fake embeddings (monkeypatched at the node module) and a scripted
LLM; runs through execute_workflow like production does (with
workspace/user identity on the context).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.engine.executor import execute_workflow
from app.schemas.workflow import Connection, Workflow, WorkflowNode


@pytest.fixture(autouse=True)
def _fake_embeddings(monkeypatch):
    import app.nodes.rag_pipeline as rp

    def fake_encode(texts):
        return [rp.__dict__ and _vec(t) for t in texts]

    def _vec(text: str) -> list[float]:
        from app.rag import fake_embed_texts

        return fake_embed_texts([text])[0] if isinstance(text, str) else text

    monkeypatch.setattr(rp, "_get_embedding_model", lambda name: object())
    monkeypatch.setattr(rp, "_embed_list", lambda model, texts: [_vec(t) for t in texts])


def _wf(collection: str = "team-kb") -> Workflow:
    return Workflow(
        id="wf_rag18",
        name="rag",
        nodes=[
            WorkflowNode(id="t", type="manual_trigger", parameters={}),
            WorkflowNode(
                id="rag",
                type="rag_pipeline",
                parameters={
                    "collection_name": collection,
                    "source_type": "text",
                    "source": "The capital of France is Paris.",
                    "query": "What is the capital of France?",
                    "similarity_threshold": 0.0,
                },
                credentials={"llm": "cred_fake"},
            ),
        ],
        connections=[Connection(source="t", target="rag")],
    )


class _FakeChat:
    async def __call__(self, **kwargs):
        assert "[1]" in kwargs["messages"][0]["content"], "context must carry citation refs"
        return {"content": "Paris [1]."}


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    import app.nodes.rag_pipeline as rp

    chat = _FakeChat()

    async def runner(**kwargs):
        return await chat(**kwargs)

    monkeypatch.setattr(rp, "chat_completion", runner)


def _resolver(refs: dict):
    def resolve(_refs: dict) -> dict:
        return {"llm": {"base_url": "http://127.0.0.1:9", "model": "fake", "api_key": "x"}}
    return resolve


def _real_user(email: str) -> int:
    from app.db import get_session
    from app.models import User

    db = get_session()
    try:
        user = User(email=email, password_hash="x")
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


async def test_node_auto_provisions_in_personal_scope_and_cites(tmp_path, monkeypatch):
    user_id = _real_user("ragowner@example.com")
    result = await execute_workflow(
        _wf(), [{}], execution_id="exec_rag18",
        user_id=user_id,
        credential_resolver=_resolver({"llm": "x"}),
    )
    assert result.status == "success", str(result.node_errors)
    item = result.results["rag"]["main"][0]
    assert item["answer"] == "Paris [1]."
    assert item["citations"], "answer must carry citations"
    assert item["citations"][0]["ref"] == 1
    assert item["chunks_used"] >= 1

    # The registry holds an owner-scoped collection with an opaque store name.
    from app.db import get_session
    from app.models import RagCollection

    db = get_session()
    try:
        recs = db.query(RagCollection).filter(RagCollection.name == "team-kb").all()
        rec = next(r for r in recs if r.owner_user_id == user_id)
        assert rec.workspace_id is None  # personal scope
        assert rec.store_name.startswith("rcstore_")
    finally:
        db.close()


async def test_second_run_does_not_duplicate_chunks(tmp_path, monkeypatch):
    user_id = _real_user("ragdupe@example.com")
    for i in range(3):
        result = await execute_workflow(
            _wf(), [{}], execution_id=f"exec_rag18_{i}",
            user_id=user_id,
            credential_resolver=_resolver({}),
        )
        assert result.status == "success", str(result.node_errors)

    from app.db import get_session
    from app.models import RagCollection
    from app.vectorstores import get_vector_store

    db = get_session()
    try:
        rec = db.query(RagCollection).filter(
            RagCollection.owner_user_id == user_id).one()
    finally:
        db.close()
    store = get_vector_store()
    handle = store.ensure_collection(rec.store_name, 384)
    # One source, chunked to one piece, re-ingested 3 times -> exactly 1 chunk.
    assert store.count(handle) == 1


async def test_legacy_engine_use_without_identity_still_runs(tmp_path, monkeypatch):
    """Bare engine tests (no user/workspace) keep the legacy direct-name path."""
    result = await execute_workflow(
        _wf("legacy-kb"), [{}], execution_id="exec_legacy",
        credential_resolver=_resolver({}),
    )
    assert result.status == "success", str(result.node_errors)
    item = result.results["rag"]["main"][0]
    assert "Paris" in item["answer"]
