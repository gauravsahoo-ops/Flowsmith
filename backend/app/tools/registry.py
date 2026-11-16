"""Tool registry and risk metadata.

The existing ``app.ai.tools.TOOLS`` registry remains the execution source of
truth during the migration. This module adds the metadata the Tool Gateway
needs: risk class, idempotency, timeout, and output cap.

No side effects: importing this module must not import ``app.ai.tools``.
"""

from __future__ import annotations

from app.platform.contracts import Idempotency, RiskClass, ToolDescriptor

# Current native tool names -> risk. Read-only tools are safe to auto-run;
# write/destructive/external-side-effect tools require policy/approval.
NATIVE_RISK: dict[str, RiskClass] = {
    "current_time": RiskClass.READ_ONLY,
    "calculator": RiskClass.READ_ONLY,
    "vector_search": RiskClass.READ_ONLY,
    "database_query": RiskClass.READ_ONLY,
    "workflow_get": RiskClass.READ_ONLY,
    "workflow_get_execution": RiskClass.READ_ONLY,
    "datatable_list": RiskClass.READ_ONLY,
    "datatable_query": RiskClass.READ_ONLY,
    "platform_list_connectors": RiskClass.READ_ONLY,
    "platform_system_health": RiskClass.READ_ONLY,
    "http_request": RiskClass.EXTERNAL_SIDE_EFFECT,
    "workflow_run": RiskClass.EXTERNAL_SIDE_EFFECT,
    "workflow_add_node": RiskClass.WRITE,
    "workflow_update_node": RiskClass.WRITE,
    "workflow_connect_nodes": RiskClass.WRITE,
    "datatable_insert_row": RiskClass.WRITE,
    "workflow_delete_node": RiskClass.DESTRUCTIVE,
}

NATIVE_IDEMPOTENCY: dict[str, Idempotency] = {
    "current_time": Idempotency.IDEMPOTENT,
    "calculator": Idempotency.IDEMPOTENT,
    "vector_search": Idempotency.IDEMPOTENT,
    "database_query": Idempotency.IDEMPOTENT,
    "workflow_get": Idempotency.IDEMPOTENT,
    "workflow_get_execution": Idempotency.IDEMPOTENT,
    "datatable_list": Idempotency.IDEMPOTENT,
    "datatable_query": Idempotency.IDEMPOTENT,
    "platform_list_connectors": Idempotency.IDEMPOTENT,
    "platform_system_health": Idempotency.IDEMPOTENT,
    "http_request": Idempotency.CONDITIONALLY_IDEMPOTENT,
    "workflow_run": Idempotency.NON_IDEMPOTENT,
    "workflow_add_node": Idempotency.CONDITIONALLY_IDEMPOTENT,
    "workflow_update_node": Idempotency.CONDITIONALLY_IDEMPOTENT,
    "workflow_connect_nodes": Idempotency.CONDITIONALLY_IDEMPOTENT,
    "datatable_insert_row": Idempotency.NON_IDEMPOTENT,
    "workflow_delete_node": Idempotency.NON_IDEMPOTENT,
}


class ToolRegistry:
    """In-memory descriptor registry used by the gateway and tests."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        if descriptor.name in self._tools:
            raise ValueError(f"Tool already registered: {descriptor.name}")
        self._tools[descriptor.name] = descriptor

    def get(self, name: str) -> ToolDescriptor | None:
        return self._tools.get(name)

    def require(self, name: str) -> ToolDescriptor:
        descriptor = self.get(name)
        if descriptor is None:
            raise KeyError(f"Unknown tool: {name}")
        return descriptor

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def list(self) -> tuple[ToolDescriptor, ...]:
        return tuple(self._tools[name] for name in self.names())

    @classmethod
    def from_native_tools(cls) -> "ToolRegistry":
        """Build descriptors from the existing native tool registry.

        The import is deliberately lazy so new platform modules can be imported
        by workers/agents without pulling in the whole tool implementation.
        """
        from app.ai.tools import TOOLS

        registry = cls()
        for name, spec in TOOLS.items():
            risk = NATIVE_RISK.get(name)
            if risk is None:
                risk = RiskClass.WRITE if spec.requires_approval else RiskClass.READ_ONLY
            registry.register(
                ToolDescriptor(
                    name=name,
                    description=spec.description,
                    input_schema=spec.parameters,
                    risk_class=risk,
                    idempotency=NATIVE_IDEMPOTENCY.get(
                        name, Idempotency.CONDITIONALLY_IDEMPOTENT
                    ),
                    source="native",
                )
            )
        return registry


def descriptor_for_tool(name: str) -> ToolDescriptor:
    """Convenience lookup for one native tool."""
    return ToolRegistry.from_native_tools().require(name)
