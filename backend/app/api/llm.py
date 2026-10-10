"""LLM Platform API Endpoints (spec: multi-provider LLM platform).

Exposes provider registry, connection testing, dynamic model discovery,
and model caching for both ephemeral forms and stored credentials.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.ai.llm_adapters import get_adapter_for_provider, get_model_cache
from app.ai.llm_registry import get_llm_registry
from app.api.auth import get_current_user
from app.api.common import ok
from app.db import get_db
from app.models import User
from app.models.credential import Credential
from app.security.crypto import decrypt_text

logger = logging.getLogger("api.llm")

router = APIRouter(prefix="/api/llm", tags=["llm"])


async def _guard_llm_base_url(adapter: Any, cred_data: dict[str, Any], variant: str) -> None:
    """SSRF guard: provider ``base_url`` is credential/user controlled and is
    fetched server-side - never allow internal/metadata hosts."""
    from app.engine.errors import NodeExecutionError
    from app.security.ssrf import assert_public_url

    try:
        base = adapter._get_base_url(cred_data, variant=variant or "")
    except Exception:
        return
    if not base:
        return
    try:
        await assert_public_url(base, node_id="llm_connection")
    except NodeExecutionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.message) from exc


class ConnectionTestRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider_id: Optional[str] = None
    provider: Optional[str] = None
    variant: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    credential_id: Optional[str] = None


class ModelDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider_id: Optional[str] = None
    provider: Optional[str] = None
    variant: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    credential_id: Optional[str] = None
    refresh: bool = False


def _resolve_credential_data(
    db: Session,
    user: Optional[User],
    credential_id: Optional[str],
    raw_provider: Optional[str],
    raw_data: dict[str, Any],
    extra_fields: Optional[dict[str, Any]] = None,
) -> tuple[str, dict[str, Any]]:
    """Helper resolving provider ID and decrypted data from either saved cred or ephemeral input."""
    merged_data = dict(raw_data)
    if extra_fields:
        for k, v in extra_fields.items():
            if k not in ("provider", "provider_id", "variant", "credential_id", "data", "refresh") and v is not None:
                merged_data.setdefault(k, v)

    if credential_id and credential_id.strip() and credential_id.strip() not in ("null", "undefined"):
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required to access saved credentials.")
        rec = db.get(Credential, credential_id.strip())
        if rec is None or rec.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Credential '{credential_id}' not found.")
        try:
            data = json.loads(decrypt_text(rec.data))
        except Exception:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Cannot decrypt credential.")
        prov = data.get("provider") or raw_provider or ("openai" if rec.type == "llm" else rec.type)
        return prov, data

    prov = raw_provider or "openai"
    return prov, merged_data


@router.get("/providers")
def list_providers(
    q: str = Query(default="", description="Search query across name, alias, category, variant"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    status: Optional[str] = Query(default=None, description="Filter by support status"),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List all registered LLM providers with metadata and search filtering."""
    registry = get_llm_registry()
    categories = registry.get_categories()
    providers = registry.search(query=q, category=category, status=status)

    out = []
    for p in providers:
        out.append({
            "id": p.provider_id,
            "provider_id": p.provider_id,
            "name": p.display_name,
            "display_name": p.display_name,
            "aliases": p.aliases,
            "category": p.category,
            "auth_type": p.auth_type,
            "credential_fields": [f.model_dump() for f in p.credential_fields],
            "base_url": p.base_url,
            "api_endpoints": p.api_endpoints,
            "model_discovery_method": p.model_discovery_method,
            "capabilities": p.capabilities,
            "variants": [v.model_dump() for v in p.variants],
            "adapter_type": p.adapter_type,
            "status": p.status,
            "catalog_count": len(p.model_catalog),
        })

    return ok({
        "total": len(out),
        "categories": categories,
        "providers": out,
    })


@router.get("/providers/{provider_id}")
def get_provider(
    provider_id: str,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve detailed provider definition and static catalog."""
    registry = get_llm_registry()
    provider = registry.get(provider_id)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"LLM Provider '{provider_id}' not found.")

    return ok({
        "id": provider.provider_id,
        "provider_id": provider.provider_id,
        "name": provider.display_name,
        "display_name": provider.display_name,
        "aliases": provider.aliases,
        "category": provider.category,
        "auth_type": provider.auth_type,
        "credential_fields": [f.model_dump() for f in provider.credential_fields],
        "base_url": provider.base_url,
        "api_endpoints": provider.api_endpoints,
        "model_discovery_method": provider.model_discovery_method,
        "capabilities": provider.capabilities,
        "variants": [v.model_dump() for v in provider.variants],
        "regional_configuration": provider.regional_configuration,
        "model_catalog": [m.model_dump() for m in provider.model_catalog],
        "adapter_type": provider.adapter_type,
        "status": provider.status,
    })


@router.post("/test-connection")
async def test_connection(
    body: ConnectionTestRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Test connection using ephemeral form data or an existing saved credential."""
    extra = body.model_extra or {}
    prov_id = body.provider_id or body.provider or extra.get("provider")
    if body.credential_id and not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required to test saved credentials.")

    provider_id, cred_data = _resolve_credential_data(
        db, user, body.credential_id, prov_id, body.data, extra
    )

    registry = get_llm_registry()
    provider = registry.get(provider_id)
    if provider is None:
        # Fallback to custom adapter if unknown provider
        provider = registry.get("custom")
    if provider is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"LLM provider '{provider_id}' is not recognized and custom provider is unavailable.",
        )

    adapter = get_adapter_for_provider(provider)
    # All DB reads (credential decryption) are done; release the session so
    # the SSRF DNS guard and provider HTTP call never hold a pooled
    # connection open (get_db closes it again on teardown).
    db.close()
    await _guard_llm_base_url(adapter, cred_data, body.variant)
    result = await adapter.test_connection(cred_data, variant=body.variant)
    return ok(result)


@router.post("/discover-models")
async def discover_models(
    body: ModelDiscoveryRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Fetch and normalize models for a provider with server-side caching."""
    extra = body.model_extra or {}
    prov_id = body.provider_id or body.provider or extra.get("provider")
    if body.credential_id and not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required to discover models for saved credentials.")

    provider_id, cred_data = _resolve_credential_data(
        db, user, body.credential_id, prov_id, body.data, extra
    )

    registry = get_llm_registry()
    provider = registry.get(provider_id)
    if provider is None:
        provider = registry.get("custom")
    if provider is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"LLM provider '{provider_id}' is not recognized and custom provider is unavailable.",
        )

    cache = get_model_cache()
    # Cache key uses user ID + credential ID or secret hash (never raw secret)
    user_prefix = str(user.id) if user else "anon"
    cache_id = body.credential_id or f"{user_prefix}_{hash(json.dumps(cred_data, sort_keys=True, default=str))}"

    # All DB reads are done; everything below is network I/O (Redis cache,
    # SSRF DNS guard, provider HTTP) and must not hold a DB connection.
    db.close()

    if not body.refresh:
        cached = await cache.get(provider.provider_id, body.variant, cache_id)
        if cached is not None:
            return ok({
                "provider_id": provider.provider_id,
                "variant": body.variant,
                "count": len(cached),
                "cached": True,
                "models": [m.model_dump() for m in cached],
            })

    adapter = get_adapter_for_provider(provider)
    await _guard_llm_base_url(adapter, cred_data, body.variant)
    models = await adapter.discover_models(cred_data, variant=body.variant)

    # Cache successful discoveries
    if models:
        await cache.set(provider.provider_id, body.variant, cache_id, models)

    return ok({
        "provider_id": provider.provider_id,
        "variant": body.variant,
        "count": len(models),
        "cached": False,
        "models": [m.model_dump() for m in models],
    })


@router.get("/credentials/{credential_id}/models")
async def get_credential_models(
    credential_id: str,
    refresh: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get discovered models associated with a saved credential."""
    req = ModelDiscoveryRequest(credential_id=credential_id, refresh=refresh)
    return await discover_models(req, user=user, db=db)


@router.post("/credentials/{credential_id}/refresh-models")
async def refresh_credential_models(
    credential_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Force-refresh and cache models associated with a saved credential."""
    req = ModelDiscoveryRequest(credential_id=credential_id, refresh=True)
    return await discover_models(req, user=user, db=db)
