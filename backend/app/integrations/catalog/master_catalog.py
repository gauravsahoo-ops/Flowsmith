"""Master Integration Catalog Engine (Phase 4).

Aggregates seed integrations with live registered FlowSmith connectors
and built-in nodes. Exposes search, filtering, and export to JSON/dict.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from app.integrations.catalog.schema import (
    CertificationLevel,
    ExternalSources,
    FlowsmithSupportStatus,
    IntegrationCategory,
    IntegrationDefinition,
    OperationSpec,
    SourcePresence,
    SupportType,
    TriggerSpec,
)
from app.integrations.catalog.data import get_seed_integrations

logger = logging.getLogger("integrations.catalog")

_catalog_instance: Optional[MasterIntegrationCatalog] = None


class MasterIntegrationCatalog:
    """Canonical registry holding all integrations, external source mappings,
    and capability metadata."""

    def __init__(self) -> None:
        self._integrations: Dict[str, IntegrationDefinition] = {}
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return

        # 1. Load seed integrations
        for item in get_seed_integrations():
            self._integrations[item.id] = item

        # 2. Merge with live FlowSmith connector registry
        try:
            from app.connectors import get_registry, register_builtin_connectors
            register_builtin_connectors()
            reg = get_registry()
            for defn in reg.list_definitions():
                key = defn.connector_key
                if key in self._integrations:
                    # Update active status & operations count
                    existing = self._integrations[key]
                    existing.flowsmith_support.is_active = True
                    existing.flowsmith_support.connector_key = key
                    existing.sources.flowsmith.supported = True
                    existing.sources.flowsmith.operation_count = len(defn.operations)
                    existing.sources.flowsmith.trigger_count = len(defn.triggers)
                else:
                    from pathlib import Path
                    gen_path = Path(__file__).resolve().parent.parent.parent / "connectors" / "generated" / f"gen_{key}_connector.py"
                    is_gen = key.startswith("gen_") or gen_path.is_file()
                    supp_type = SupportType.GENERATED if is_gen else SupportType.NATIVE
                    category_val = IntegrationCategory.CRM
                    cat_lower = (defn.category or "").lower()
                    if "communication" in cat_lower or "chat" in cat_lower:
                        category_val = IntegrationCategory.COMMUNICATION
                    elif "productivity" in cat_lower:
                        category_val = IntegrationCategory.PRODUCTIVITY
                    elif "database" in cat_lower or "storage" in cat_lower:
                        category_val = IntegrationCategory.DATABASE_STORAGE
                    elif "developer" in cat_lower or "devops" in cat_lower:
                        category_val = IntegrationCategory.DEVELOPER_DEVOPS
                    elif "finance" in cat_lower:
                        category_val = IntegrationCategory.FINANCE_COMMERCE
                    elif "ai" in cat_lower:
                        category_val = IntegrationCategory.AI_VECTOR
                    elif "api" in cat_lower:
                        category_val = IntegrationCategory.PUBLIC_APIS

                    ops = [
                        OperationSpec(
                            key=op_k,
                            name=op_v.display_name,
                            description=op_v.description,
                            idempotent=op_v.idempotency == "idempotent",
                            action_type="action"
                        )
                        for op_k, op_v in defn.operations.items()
                    ]
                    trigs = [
                        TriggerSpec(
                            key=tr_k,
                            name=tr_k.replace("_", " ").title(),
                            description=f"Trigger for {tr_k}",
                            trigger_type=tr_v.trigger_type
                        )
                        for tr_k, tr_v in defn.triggers.items()
                    ]

                    self._integrations[key] = IntegrationDefinition(
                        id=key,
                        name=defn.display_name,
                        vendor=defn.display_name.split()[0],
                        category=category_val,
                        subcategory="Registered Connector",
                        description=defn.description,
                        operations=ops,
                        triggers=trigs,
                        sources=ExternalSources(
                            flowsmith=SourcePresence(supported=True, connector_id=key, operation_count=len(ops), trigger_count=len(trigs))
                        ),
                        flowsmith_support=FlowsmithSupportStatus(
                            support_type=supp_type,
                            certification=CertificationLevel.VALIDATED,
                            is_active=True,
                            connector_key=key,
                            node_slugs=[key]
                        )
                    )
        except Exception as e:
            logger.warning("Failed to auto-discover connectors into catalog: %s", e)

        self._initialized = True

    def list_all(self) -> List[IntegrationDefinition]:
        self.initialize()
        return list(self._integrations.values())

    def get(self, integration_id: str) -> Optional[IntegrationDefinition]:
        self.initialize()
        return self._integrations.get(integration_id)

    def search(self, query: str) -> List[IntegrationDefinition]:
        self.initialize()
        q = query.lower().strip()
        if not q:
            return self.list_all()

        results = []
        for item in self._integrations.values():
            if (
                q in item.id.lower()
                or q in item.name.lower()
                or q in item.vendor.lower()
                or q in item.category.value.lower()
                or any(q in op.name.lower() or q in op.key.lower() for op in item.operations)
                or any(q in tr.name.lower() or q in tr.key.lower() for tr in item.triggers)
                or any(q in c.lower() for c in item.capabilities)
            ):
                results.append(item)
        return results

    def to_json_dict(self) -> Dict:
        self.initialize()
        items = [i.model_dump() for i in self._integrations.values()]
        return {
            "total_integrations": len(items),
            "integrations": items
        }


def get_master_catalog() -> MasterIntegrationCatalog:
    global _catalog_instance
    if _catalog_instance is None:
        _catalog_instance = MasterIntegrationCatalog()
        _catalog_instance.initialize()
    return _catalog_instance
