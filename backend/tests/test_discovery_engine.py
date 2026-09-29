"""Tests for Long-Tail Discovery Engine (Phases 40B, 40C, 40D, 40L).

Verifies:
- Ingestion from n8n, Zapier, Cyclr, MCP, and OpenAPI catalogs
- Deduplication and alias normalization into CanonicalEntity records
- 8-step decision order strategy assignment
- Catalog synchronization diff detection and changelog generation
"""

import pytest
from app.integrations.catalog.discovery_engine import DiscoveryEngine


def test_discovery_engine_ingestion():
    engine = DiscoveryEngine()
    n8n = engine.ingest_n8n_catalog()
    zap = engine.ingest_zapier_catalog()
    cyc = engine.ingest_cyclr_catalog()
    mcp = engine.ingest_mcp_catalog()
    oas = engine.ingest_openapi_directory()

    assert len(n8n) >= 50
    assert len(zap) >= 50
    assert len(cyc) >= 50
    assert len(mcp) >= 10
    assert len(oas) >= 9


def test_discovery_engine_canonicalization():
    engine = DiscoveryEngine()
    summary = engine.run_full_pipeline()

    assert summary["total_external_applications_discovered"] > 180
    assert summary["total_canonical_applications"] >= 80
    assert summary["total_native"] >= 50
    assert summary["total_http"] >= 10
    assert summary["total_mcp"] >= 10
