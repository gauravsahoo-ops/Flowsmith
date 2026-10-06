"""Canonical Integration Catalog Schema (Phase 4).

Defines the normalized entities for the Master Integration Catalog.
Every external service, SaaS app, API, protocol, or data system is
represented by a standardized IntegrationDefinition.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class IntegrationCategory(str, Enum):
    CRM = "CRM & Sales"
    PRODUCTIVITY = "Productivity & Collaboration"
    COMMUNICATION = "Communication & Messaging"
    EMAIL_MARKETING = "Email & Marketing"
    DEVELOPER_DEVOPS = "Developer & DevOps"
    DATABASE_STORAGE = "Database & Cloud Storage"
    AI_VECTOR = "AI & Vector Search"
    FINANCE_COMMERCE = "Finance & Commerce"
    CUSTOMER_SUPPORT = "Customer Support & Success"
    CORE_LOGIC = "Core Logic & Routing"
    DATA_TRANSFORMATION = "Data Transformation"
    PROTOCOLS = "Protocols & Network"
    PUBLIC_APIS = "Public & Open APIs"
    UTILITIES = "Utilities & Security"


class AuthType(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    BASIC_AUTH = "basic_auth"
    OAUTH2 = "oauth2"
    OAUTH1 = "oauth1"
    CUSTOM_HEADER = "custom_header"
    MTLS = "mtls"
    SESSION_COOKIE = "session_cookie"


class SupportType(str, Enum):
    NATIVE = "native"
    GENERATED = "generated"
    OPENAPI = "openapi"
    UNIVERSAL_HTTP = "universal_http"
    MCP = "mcp"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


class CertificationLevel(str, Enum):
    DISCOVERED = "discovered"
    GENERATED = "generated"
    VALIDATED = "validated"
    TESTED = "tested"
    CERTIFIED = "certified"
    DEPRECATED = "deprecated"


class ImplementationMethod(str, Enum):
    EXISTING_NATIVE = "EXISTING_NATIVE"
    EXISTING_GENERATED = "EXISTING_GENERATED"
    OPENAPI_GENERATABLE = "OPENAPI_GENERATABLE"
    REST_GENERATABLE = "REST_GENERATABLE"
    UNIVERSAL_HTTP = "UNIVERSAL_HTTP"
    MCP = "MCP"
    NATIVE_REQUIRED = "NATIVE_REQUIRED"
    BLOCKED = "BLOCKED"
    UNVERIFIED = "UNVERIFIED"


class OperationCoverageStatus(str, Enum):
    EXACT = "EXACT"
    EQUIVALENT = "EQUIVALENT"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"
    UNSUPPORTED = "UNSUPPORTED"


class SourcePresence(BaseModel):
    supported: bool = False
    connector_id: Optional[str] = None
    app_id: Optional[str] = None
    operation_count: int = 0
    trigger_count: int = 0
    action_count: int = 0
    search_count: int = 0
    webhook_count: int = 0
    auth_types: List[str] = Field(default_factory=list)
    documentation_url: Optional[str] = None
    notes: str = ""


class ExternalSources(BaseModel):
    n8n: SourcePresence = Field(default_factory=SourcePresence)
    zapier: SourcePresence = Field(default_factory=SourcePresence)
    cyclr: SourcePresence = Field(default_factory=SourcePresence)
    flowsmith: SourcePresence = Field(default_factory=SourcePresence)


class FlowsmithSupportStatus(BaseModel):
    support_type: SupportType = SupportType.UNVERIFIED
    certification: CertificationLevel = CertificationLevel.DISCOVERED
    is_active: bool = False
    connector_key: Optional[str] = None
    node_slugs: List[str] = Field(default_factory=list)
    has_e2e_test: bool = False
    has_contract_test: bool = False
    notes: str = ""


class OperationSpec(BaseModel):
    key: str
    name: str
    description: str
    is_supported: bool = True
    idempotent: bool = False
    action_type: str = "action"  # "action", "search", "crud", "rpc"


class TriggerSpec(BaseModel):
    key: str
    name: str
    description: str
    is_supported: bool = True
    trigger_type: str = "webhook"  # "webhook", "polling", "event_stream"


class IntegrationDefinition(BaseModel):
    """The master normalized entity representing an application or integration."""
    id: str
    name: str
    canonical_name: str = ""
    vendor: str
    category: IntegrationCategory
    subcategory: str = "General"
    description: str = ""
    website: str = ""
    official_url: str = ""
    documentation_url: str = ""
    icon: Optional[str] = None
    color: str = "#4F46E5"

    authentication: List[AuthType] = Field(default_factory=lambda: [AuthType.API_KEY])
    operations: List[OperationSpec] = Field(default_factory=list)
    actions: List[OperationSpec] = Field(default_factory=list)
    searches: List[OperationSpec] = Field(default_factory=list)
    triggers: List[TriggerSpec] = Field(default_factory=list)
    webhooks: List[TriggerSpec] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)

    pagination: List[str] = Field(default_factory=list)
    special_capabilities: List[str] = Field(default_factory=list)
    ai_capabilities: List[str] = Field(default_factory=list)
    database_capabilities: List[str] = Field(default_factory=list)
    storage_capabilities: List[str] = Field(default_factory=list)

    implementation_priority: float = 0.0
    implementation_method: ImplementationMethod = ImplementationMethod.UNVERIFIED

    sources: ExternalSources = Field(default_factory=ExternalSources)
    flowsmith_support: FlowsmithSupportStatus = Field(default_factory=FlowsmithSupportStatus)

    def model_post_init(self, __context: Any) -> None:
        if not self.canonical_name:
            self.canonical_name = self.name
        if not self.official_url and self.website:
            self.official_url = self.website
        if not self.actions:
            self.actions = [op for op in self.operations if op.action_type in ("action", "crud", "rpc")]
        if not self.searches:
            self.searches = [op for op in self.operations if op.action_type == "search"]
        if not self.webhooks:
            self.webhooks = [tr for tr in self.triggers if tr.trigger_type == "webhook"]
