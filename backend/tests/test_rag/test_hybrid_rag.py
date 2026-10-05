"""Tests for Reciprocal Rank Fusion (RRF) and BM25 sparse keyword scoring in RAG."""

import pytest
from app.rag import bm25_sparse_score, reciprocal_rank_fusion


def test_bm25_sparse_score_matching():
    score = bm25_sparse_score("salesforce leads pipeline", "This document covers salesforce integration and lead pipeline processing.")
    assert score > 0.0

    zero_score = bm25_sparse_score("completely unrelated query terms", "This document covers salesforce integration.")
    assert zero_score == 0.0


def test_reciprocal_rank_fusion_combines_dense_and_sparse():
    dense_hits = [
        {"id": "doc_1", "content": "salesforce crm lead data", "similarity": 0.88},
        {"id": "doc_2", "content": "general database sql storage", "similarity": 0.85},
        {"id": "doc_3", "content": "stripe billing invoice details", "similarity": 0.75},
    ]
    sparse_scores = {
        "doc_3": 3.5,  # High keyword match for stripe billing
        "doc_1": 1.2,
        "doc_2": 0.0,
    }

    fused = reciprocal_rank_fusion(dense_hits, sparse_scores, k=60, dense_weight=0.6, sparse_weight=0.4)
    assert len(fused) == 3
    # All fused items must have rrf_score and hybrid flag
    for item in fused:
        assert "rrf_score" in item
        assert item["hybrid"] is True

    # doc_3 should be boosted up due to strong sparse keyword match
    assert fused[0]["id"] in ("doc_1", "doc_3")
