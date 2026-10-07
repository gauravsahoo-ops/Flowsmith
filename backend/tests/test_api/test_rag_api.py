"""Phase 18 — RAG collections API, full stack.

CRUD + ingest + query over HTTP with deterministic hash embeddings
(monkeypatched), proving: tenant scoping end to end, 404 (not 403) for
cross-tenant probes, debugging telemetry in responses.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_api.conftest import auth_headers, register


@pytest.fixture(autouse=True)
def _fake_embeddings(monkeypatch):
    """Deterministic embeddings for the API layer (no AI extras)."""
    from app import rag as rag_service

    monkeypatch.setattr(rag_service, "embed_texts", rag_service.fake_embed_texts)


def _setup(client: TestClient, email="ragapi@example.com"):
    token = auth_headers(register(client, email=email)["token"])
    return token


def _mk_collection(client, token, name="kb", workspace_id=None) -> dict:
    resp = client.post("/api/rag/collections",
                       json={"name": name, "workspace_id": workspace_id},
                       headers=token)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _ingest(client, token, collection_id, text, doc_id=None) -> dict:
    body: dict = {"documents": [{"text": text}]}
    if doc_id:
        body["documents"][0]["id"] = doc_id
    resp = client.post(f"/api/rag/collections/{collection_id}/documents",
                       json=body, headers=token)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ----------------------------------------------------------------------
# CRUD + scoping
# ----------------------------------------------------------------------

def test_collection_crud_roundtrip(client):
    token = _setup(client)
    rec = _mk_collection(client, token, "my-kb")
    # The opaque physical store name never leaves the server.
    assert "store_name" not in rec

    listed = client.get("/api/rag/collections", headers=token).json()["data"]
    assert [r["id"] for r in listed] == [rec["id"]]

    got = client.get(f"/api/rag/collections/{rec['id']}", headers=token).json()["data"]
    assert got["name"] == "my-kb"

    deleted = client.delete(f"/api/rag/collections/{rec['id']}", headers=token)
    assert deleted.status_code == 200
    gone = client.get(f"/api/rag/collections/{rec['id']}", headers=token)
    assert gone.status_code == 404


def test_cross_tenant_access_is_404_not_403(client):
    alice = _setup(client, "alice@x.example.com")
    bob = _setup(client, "bob@x.example.com")
    rec = _mk_collection(client, alice, "secret-kb")

    # Bob cannot list it...
    ids = [r["id"] for r in
           client.get("/api/rag/collections", headers=bob).json()["data"]]
    assert rec["id"] not in ids
    # ...nor read, query, ingest, or delete it. Every probe is a 404 so
    # the collection's existence never leaks across tenants.
    assert client.get(f"/api/rag/collections/{rec['id']}", headers=bob).status_code == 404
    assert client.post(
        f"/api/rag/collections/{rec['id']}/query",
        json={"query": "hello"}, headers=bob,
    ).status_code == 404
    assert client.post(
        f"/api/rag/collections/{rec['id']}/documents",
        json={"documents": [{"text": "intrude"}]}, headers=bob,
    ).status_code == 404
    assert client.delete(f"/api/rag/collections/{rec['id']}", headers=bob).status_code == 404


def test_ingest_query_and_stats_over_http(client):
    token = _setup(client)
    rec = _mk_collection(client, token, "docs")
    result = _ingest(client, token, rec["id"],
                     "The Eiffel Tower is in Paris.", doc_id="eiffel")
    assert result["chunks_upserted"] >= 1
    assert "embed" in result["timing_ms"]

    # Idempotent re-ingest: same id -> no duplication.
    _ingest(client, token, rec["id"], "Different text entirely.", doc_id="eiffel")
    stats = client.get(f"/api/rag/collections/{rec['id']}/stats", headers=token).json()["data"]
    assert stats["chunks"] == 1
    assert stats["documents"] == ["eiffel"]

    q = client.post(f"/api/rag/collections/{rec['id']}/query",
                    json={"query": "totally unrelated"}, headers=token)
    assert q.status_code == 200
    data = q.json()["data"]
    assert data["debug"]["after_threshold"] <= data["debug"]["total_candidates"]
    assert "timing_ms" in data["debug"]


def test_delete_document_and_reindex_flow(client):
    token = _setup(client)
    rec = _mk_collection(client, token, "flow")
    _ingest(client, token, rec["id"], "v1 of the policy", doc_id="policy-1")
    reindexed = client.post(
        f"/api/rag/collections/{rec['id']}/documents/policy-1/reindex",
        json={"text": "v2 of the policy"}, headers=token)
    assert reindexed.status_code == 200
    stats = client.get(f"/api/rag/collections/{rec['id']}/stats", headers=token).json()["data"]
    assert stats["chunks"] == 1

    removed = client.delete(
        f"/api/rag/collections/{rec['id']}/documents/policy-1", headers=token)
    assert removed.status_code == 200
    stats2 = client.get(f"/api/rag/collections/{rec['id']}/stats", headers=token).json()["data"]
    assert stats2["chunks"] == 0


def test_validation_errors_are_422(client):
    token = _setup(client)
    rec = _mk_collection(client, token, "v")
    empty = client.post(f"/api/rag/collections/{rec['id']}/documents",
                        json={"documents": [{"text": "   "}]}, headers=token)
    assert empty.status_code == 422
    blank_query = client.post(f"/api/rag/collections/{rec['id']}/query",
                              json={"query": ""}, headers=token)
    assert blank_query.status_code == 422


def test_ingest_bounds_are_422(client):
    """Unbounded ingest is a DoS vector: doc count and size are capped."""
    token = _setup(client)
    rec = _mk_collection(client, token, "bounds")
    too_many = client.post(
        f"/api/rag/collections/{rec['id']}/documents",
        json={"documents": [{"text": f"d{i}"} for i in range(201)]},
        headers=token,
    )
    assert too_many.status_code == 422
    too_big = client.post(
        f"/api/rag/collections/{rec['id']}/documents",
        json={"documents": [{"text": "x" * (2_000_001)}]},
        headers=token,
    )
    assert too_big.status_code == 422
    oversized_body = client.post(
        f"/api/rag/collections/{rec['id']}/documents/some_doc/reindex",
        json={"text": "y" * (2_000_001)},
        headers=token,
    )
    assert oversized_body.status_code == 422
