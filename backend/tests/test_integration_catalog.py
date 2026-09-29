"""Unit and integration tests for FlowSmith Universal Integration Platform (Phase 4, 6, 23).

Tests:
- Canonical Node Contract introspection
- Master Integration Catalog loading, search, and indexing
- Coverage Engine matrix calculation (n8n, Zapier, Cyclr)
- Integration API endpoints (/api/integrations/*)
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.engine.canonical_contract import from_base_node, CanonicalNodeDefinition
from app.nodes.registry import NODE_REGISTRY, _load_builtin_nodes
from app.integrations.catalog import get_master_catalog, MasterIntegrationCatalog
from app.integrations.coverage import CoverageEngine
from tests.test_api.conftest import register, auth_headers

_load_builtin_nodes()


def test_canonical_node_contract_introspection():
    """Verify built-in nodes convert to valid CanonicalNodeDefinition schemas."""
    # Test HTTP Request node
    http_cls = NODE_REGISTRY["http_request"]
    canonical_http = from_base_node(http_cls)
    assert isinstance(canonical_http, CanonicalNodeDefinition)
    assert canonical_http.slug == "http_request"
    assert canonical_http.category in ("Protocols", "Network", "General", "Actions")
    assert len(canonical_http.inputs.ports) >= 1
    assert len(canonical_http.outputs.ports) >= 1
    assert canonical_http.execution.default_timeout_seconds > 0
    assert canonical_http.ai.agent_compatible is True

    # Test Filter node
    filter_cls = NODE_REGISTRY["filter"]
    canonical_filter = from_base_node(filter_cls)
    assert canonical_filter.slug == "filter"
    assert "conditions" in [f.name for f in canonical_filter.configuration_fields] or len(canonical_filter.configuration_fields) > 0


def test_master_catalog_search_and_filter():
    """Verify Master Integration Catalog queries and fuzzy search."""
    catalog = get_master_catalog()
    all_items = catalog.list_all()
    assert len(all_items) >= 60

    # Search for Salesforce
    sf_results = catalog.search("salesforce")
    assert any(i.id == "salesforce" for i in sf_results)
    sf_item = catalog.get("salesforce")
    assert sf_item is not None
    assert sf_item.flowsmith_support.is_active is True
    assert sf_item.sources.n8n.supported is True
    assert sf_item.sources.zapier.supported is True
    assert sf_item.sources.cyclr.supported is True

    # Search for Slack
    slack_results = catalog.search("slack")
    assert any(i.id == "slack" for i in slack_results)


def test_coverage_engine_metrics():
    """Verify empirical coverage engine analysis without fake completeness."""
    engine = CoverageEngine()
    analysis = engine.analyze()
    summary = analysis["summary"]

    assert summary["flowsmith_total_supported"] >= 68
    assert summary["flowsmith_native"] >= 50
    assert summary["flowsmith_generated"] >= 15
    assert summary["missing_count"] >= 0

    ext = analysis["external_comparisons"]
    assert ext["n8n"]["total_in_catalog"] > 0
    assert ext["zapier"]["total_in_catalog"] > 0
    assert ext["cyclr"]["total_in_catalog"] > 0
    assert ext["all_three_overlap_count"] >= 10


def test_api_integrations_endpoints(client):
    """Verify /api/integrations REST endpoints."""
    # Create user and get auth header
    auth_data = register(client)
    headers = auth_headers(auth_data["token"])

    # 1. Catalog list
    res_cat = client.get("/api/integrations/catalog", headers=headers)
    assert res_cat.status_code == 200
    cat_data = res_cat.json()
    assert "data" in cat_data
    assert len(cat_data["data"]) >= 60

    # 2. Single item lookup
    res_item = client.get("/api/integrations/catalog/salesforce", headers=headers)
    assert res_item.status_code == 200
    assert res_item.json()["data"]["id"] == "salesforce"

    # 3. Coverage endpoint
    res_cov = client.get("/api/integrations/coverage", headers=headers)
    assert res_cov.status_code == 200
    cov_data = res_cov.json()["data"]
    assert "flowsmith_total_supported" in cov_data["summary"]

    # 4. Certification endpoint
    res_cert = client.get("/api/integrations/certification", headers=headers)
    assert res_cert.status_code == 200
    cert_data = res_cert.json()["data"]
    assert len(cert_data) >= 68

    # 5. Canonical nodes endpoint
    res_nodes = client.get("/api/integrations/canonical-nodes", headers=headers)
    assert res_nodes.status_code == 200
    nodes_data = res_nodes.json()["data"]
    assert len(nodes_data) >= 60

