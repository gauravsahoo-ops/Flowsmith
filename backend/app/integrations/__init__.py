"""FlowSmith Universal Integration Platform (spec 40+)."""

from app.integrations.catalog import (
    IntegrationCategory,
    IntegrationDefinition,
    MasterIntegrationCatalog,
    get_master_catalog,
)

__all__ = [
    "IntegrationCategory",
    "IntegrationDefinition",
    "MasterIntegrationCatalog",
    "get_master_catalog",
]
