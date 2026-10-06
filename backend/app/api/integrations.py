"""Universal Integration Catalog and Coverage API endpoints (Phase 4, 6, 23).

Exposes:
- GET /api/integrations/catalog: Query Master Integration Catalog with external sources
- GET /api/integrations/catalog/{id}: Integration details
- GET /api/integrations/coverage: Complete coverage matrix vs n8n, Zapier, Cyclr
- GET /api/integrations/certification: Certification levels (Certified, Validated, Generated)
- GET /api/integrations/canonical-nodes: Canonical Node Contract representations
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from app.api.auth import get_current_user
from app.api.common import ok
from app.models import User
from app.integrations.catalog import get_master_catalog
from app.integrations.coverage import CoverageEngine
from app.nodes.registry import NODE_REGISTRY
from app.engine.canonical_contract import from_base_node

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("/catalog")
def get_catalog(
    q: Optional[str] = Query(None, description="Fuzzy search across integrations"),
    category: Optional[str] = Query(None, description="Filter by category (CRM, ERP, Finance, AI, Database, Productivity, Developer, Storage)"),
    auth: Optional[str] = Query(None, description="Filter by authentication scheme (oauth2, api_key, basic, bearer)"),
    has_trigger: Optional[bool] = Query(None, description="Filter by trigger availability"),
    has_search: Optional[bool] = Query(None, description="Filter by search capability"),
    has_webhook: Optional[bool] = Query(None, description="Filter by webhook availability"),
    connector_type: Optional[str] = Query(None, description="Filter by connector type (native, generated, openapi, http, mcp)"),
    certification: Optional[str] = Query(None, description="Filter by certification status"),
    user: User = Depends(get_current_user),
) -> dict:
    """List or search the master integration catalog with rich multi-dimensional filters."""
    catalog = get_master_catalog()
    if q:
        items = catalog.search(q)
    else:
        items = catalog.list_all()

    if category:
        items = [i for i in items if category.lower() in (i.category.value if hasattr(i.category, "value") else str(i.category)).lower()]

    if auth:
        items = [
            i for i in items
            if any(auth.lower() in (a.value if hasattr(a, "value") else str(a)).lower() for a in i.authentication)
        ]

    if has_trigger is not None:
        items = [i for i in items if (len(i.triggers) > 0) == has_trigger]

    if has_search is not None:
        items = [i for i in items if (len(i.searches) > 0) == has_search]

    if has_webhook is not None:
        items = [i for i in items if (len(i.webhooks) > 0) == has_webhook]

    if connector_type:
        ctype = connector_type.lower()
        items = [
            i for i in items
            if ctype in str(getattr(getattr(i, "flowsmith_support", None), "support_type", "")).lower()
        ]

    if certification:
        cert_target = certification.lower()
        items = [
            i for i in items
            if cert_target in str(getattr(getattr(i, "flowsmith_support", None), "certification", "")).lower()
        ]

    return ok([i.model_dump() for i in items])


@router.get("/discovery")
def get_discovery_overview(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns canonical multi-ecosystem application registry and discovery metrics."""
    import json
    from pathlib import Path
    disc_file = Path(r"c:\Flowsmith\docs\integration-platform\CANONICAL_APPLICATION_REGISTRY.json")
    if disc_file.exists():
        with open(disc_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ok(data)
    return ok({"summary": {}, "applications": []})


@router.get("/catalog/{integration_id}")
def get_catalog_item(
    integration_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get single integration details from the catalog."""
    catalog = get_master_catalog()
    item = catalog.get(integration_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Integration '{integration_id}' not found in catalog."
        )
    return ok(item.model_dump())


@router.get("/coverage")
def get_coverage(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns coverage analysis across FlowSmith, n8n, Zapier, and Cyclr."""
    engine = CoverageEngine()
    analysis = engine.analyze()
    return ok(analysis)


@router.get("/certification")
def get_certifications(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns authoritative certification matrix and reconciled metrics for all active connectors (Phase 43)."""
    from app.integrations.catalog.certification_state_machine import get_certification_summary

    payload = get_certification_summary()
    return ok(payload)



@router.get("/canonical-nodes")
def get_canonical_nodes(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns canonical node contracts for all built-in nodes."""
    canonical_list = []
    for node_cls in NODE_REGISTRY.values():
        canonical_list.append(from_base_node(node_cls).model_dump())

    canonical_list.sort(key=lambda x: (x["category"], x["slug"]))
    return ok(canonical_list)
