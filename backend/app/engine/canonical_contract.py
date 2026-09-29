"""Canonical FlowSmith Node Contract (Phase 2).

Defines the universal declarative contract for every node in FlowSmith.
Every node (built-in flow, logic, transform, protocol, AI, or connector-backed)
must be representable by this common schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RuntimeType(str, Enum):
    BUILTIN_NODE = "builtin_node"
    CONNECTOR_ACTION = "connector_action"
    CONNECTOR_TRIGGER = "connector_trigger"
    SANDBOX_CODE = "sandbox_code"
    SUB_WORKFLOW = "sub_workflow"
    AI_AGENT = "ai_agent"
    MCP_TOOL = "mcp_tool"


class IdempotencyLevel(str, Enum):
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"
    CONDITIONALLY_IDEMPOTENT = "conditionally_idempotent"
    UNKNOWN = "unknown"


class BatchSemantics(str, Enum):
    ITEM_BY_ITEM = "item_by_item"
    ALL_ITEMS = "all_items"
    CHUNKS = "chunks"


class NodePort(BaseModel):
    name: str = "main"
    display_name: str = "Main"
    description: str = ""
    is_required: bool = True
    schema_definition: Dict[str, Any] = Field(default_factory=dict)


class NodeInputContract(BaseModel):
    ports: List[NodePort] = Field(default_factory=lambda: [NodePort()])
    batch_semantics: BatchSemantics = BatchSemantics.ALL_ITEMS
    supports_expressions: bool = True
    supports_dynamic_fields: bool = False
    required_inputs: List[str] = Field(default_factory=list)


class NodeOutputContract(BaseModel):
    ports: List[NodePort] = Field(default_factory=lambda: [NodePort()])
    supports_binary_data: bool = False
    supports_dynamic_schema: bool = False
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class NodeConfigField(BaseModel):
    name: str
    label: str
    type: str  # "string", "number", "boolean", "select", "json", "code", "credentials"
    description: str = ""
    default: Any = None
    required: bool = False
    options: List[Dict[str, Any]] = Field(default_factory=list)
    supports_expression: bool = True
    conditional_visibility: Optional[Dict[str, Any]] = None
    placeholder: str = ""


class NodeExecutionContract(BaseModel):
    executor: str = "engine"  # "engine", "sandbox_python", "sandbox_js", "connector"
    default_timeout_seconds: int = 300
    max_timeout_seconds: int = 3600
    supports_retry: bool = True
    default_max_retries: int = 3
    default_retry_backoff_seconds: float = 1.0
    idempotency: IdempotencyLevel = IdempotencyLevel.UNKNOWN
    rate_limit_per_minute: Optional[int] = None
    concurrency_limit: Optional[int] = None


class NodeErrorContract(BaseModel):
    normalized_error_types: List[str] = Field(default_factory=lambda: [
        "AuthenticationError", "AuthorizationError", "ValidationError",
        "NotFoundError", "RateLimitError", "TimeoutError", "NetworkError",
        "ProviderError", "SchemaError", "ConfigurationError", "UnknownError"
    ])
    supports_error_routing: bool = True  # Send error item to error branch
    continue_on_fail_supported: bool = True
    partial_failure_supported: bool = True


class NodeTriggerContract(BaseModel):
    is_trigger: bool = False
    trigger_type: Optional[str] = None  # "webhook", "polling", "schedule", "manual", "event"
    supports_deduplication: bool = True
    supports_checkpoint: bool = True
    supports_signature_verification: bool = False


class NodeSecurityContract(BaseModel):
    required_scopes: List[str] = Field(default_factory=list)
    credential_types: List[str] = Field(default_factory=list)
    data_classification: str = "standard"  # "standard", "confidential", "restricted"
    secret_fields: List[str] = Field(default_factory=list)
    permission_metadata: Dict[str, Any] = Field(default_factory=dict)


class NodeAIMetadata(BaseModel):
    semantic_description: str
    capability_tags: List[str] = Field(default_factory=list)
    agent_compatible: bool = True
    tool_description: str = ""
    risk_classification: str = "low"  # "low", "medium", "high", "critical"


class NodeDocumentation(BaseModel):
    documentation_url: str = ""
    authentication_guide_url: str = ""
    examples: List[Dict[str, Any]] = Field(default_factory=list)
    operation_descriptions: Dict[str, str] = Field(default_factory=dict)


class CanonicalNodeDefinition(BaseModel):
    """The Universal FlowSmith Node Contract schema."""
    id: str
    slug: str
    name: str
    display_name: str
    description: str
    version: int = 1
    category: str
    subcategory: str = "General"
    icon: Optional[str] = None
    color: str = "#4F46E5"
    node_type: str
    runtime_type: RuntimeType = RuntimeType.BUILTIN_NODE

    inputs: NodeInputContract = Field(default_factory=NodeInputContract)
    outputs: NodeOutputContract = Field(default_factory=NodeOutputContract)
    configuration_fields: List[NodeConfigField] = Field(default_factory=list)
    execution: NodeExecutionContract = Field(default_factory=NodeExecutionContract)
    errors: NodeErrorContract = Field(default_factory=NodeErrorContract)
    trigger: NodeTriggerContract = Field(default_factory=NodeTriggerContract)
    security: NodeSecurityContract = Field(default_factory=NodeSecurityContract)
    ai: NodeAIMetadata = Field(default_factory=lambda: NodeAIMetadata(semantic_description=""))
    documentation: NodeDocumentation = Field(default_factory=NodeDocumentation)


def from_base_node(node_cls: type) -> CanonicalNodeDefinition:
    """Introspect an existing BaseNode subclass and compile it into a CanonicalNodeDefinition."""
    from app.engine.node_base import BaseNode

    slug = getattr(node_cls, "node_type", "unknown")
    name = getattr(node_cls, "display_name", slug.replace("_", " ").title())
    desc = getattr(node_cls, "description", "")
    version = getattr(node_cls, "version", 1)
    category = getattr(node_cls, "category", "General")
    icon = getattr(node_cls, "icon", None)
    creds = getattr(node_cls, "credential_types", [])
    in_handles = getattr(node_cls, "input_handles", ["main"])
    out_handles = getattr(node_cls, "output_handles", ["main"])
    idempotency = getattr(node_cls, "idempotency", "unknown")

    is_trig = "trigger" in slug or category == "Triggers"
    trig_type = "manual"
    if "webhook" in slug:
        trig_type = "webhook"
    elif "schedule" in slug:
        trig_type = "schedule"
    elif is_trig:
        trig_type = "event"

    runtime = RuntimeType.BUILTIN_NODE
    if slug == "code":
        runtime = RuntimeType.SANDBOX_CODE
    elif slug in ("ai", "ai_agent"):
        runtime = RuntimeType.AI_AGENT
    elif slug == "sub_workflow":
        runtime = RuntimeType.SUB_WORKFLOW

    # Extract configuration properties from Pydantic schema if present
    config_fields: List[NodeConfigField] = []
    if hasattr(node_cls, "parameters_schema") and hasattr(node_cls.parameters_schema, "model_json_schema"):
        schema = node_cls.parameters_schema.model_json_schema()
        props = schema.get("properties", {})
        required_props = set(schema.get("required", []))
        for p_name, p_spec in props.items():
            config_fields.append(NodeConfigField(
                name=p_name,
                label=p_spec.get("title", p_name.replace("_", " ").title()),
                type=p_spec.get("type", "string"),
                description=p_spec.get("description", ""),
                default=p_spec.get("default"),
                required=p_name in required_props,
            ))

    return CanonicalNodeDefinition(
        id=f"node_{slug}",
        slug=slug,
        name=name,
        display_name=name,
        description=desc,
        version=version,
        category=category,
        icon=icon,
        node_type=slug,
        runtime_type=runtime,
        inputs=NodeInputContract(
            ports=[NodePort(name=h, display_name=h.title()) for h in in_handles]
        ),
        outputs=NodeOutputContract(
            ports=[NodePort(name=h, display_name=h.title()) for h in out_handles]
        ),
        configuration_fields=config_fields,
        execution=NodeExecutionContract(
            idempotency=IdempotencyLevel(idempotency) if idempotency in [e.value for e in IdempotencyLevel] else IdempotencyLevel.UNKNOWN
        ),
        trigger=NodeTriggerContract(
            is_trigger=is_trig,
            trigger_type=trig_type if is_trig else None
        ),
        security=NodeSecurityContract(
            credential_types=creds
        ),
        ai=NodeAIMetadata(
            semantic_description=desc or f"Performs {name} workflow operation.",
            capability_tags=[category.lower(), slug.replace("_", " ")]
        )
    )
