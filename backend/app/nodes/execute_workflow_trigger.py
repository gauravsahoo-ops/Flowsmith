"""Execute Workflow Trigger node (Flow / Triggers).

Starts the workflow when called by an Execute Sub-workflow node in another workflow.
Receives input items passed by the parent workflow and emits them to output.
Supports defining an explicit schema or accepting any data.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register, NODE_REGISTRY


class SchemaField(BaseModel):
    name: str = Field(default="", description="Field name")
    type: Literal["any", "string", "number", "boolean", "array", "object"] = Field(
        default="string", description="Field data type"
    )


class ExecuteWorkflowTriggerParams(BaseModel):
    input_data_mode: Literal["fields", "any"] = Field(
        default="fields",
        description="Input data mode: 'fields' (Define using fields below) or 'any' (Accept all data)",
    )
    schema_fields: list[SchemaField] = Field(
        default_factory=list,
        description="List of defined schema fields",
    )


@register
class ExecuteWorkflowTriggerNode(BaseNode[ExecuteWorkflowTriggerParams]):
    node_type = "execute_workflow_trigger"
    display_name = "When executed by Another Workflow"
    version = 1
    description = "Starts the workflow when called by an Execute Sub-workflow node in another workflow."
    category = "Flow"
    icon = "execute_workflow_trigger"
    parameters_schema = ExecuteWorkflowTriggerParams
    input_handles: list[str] = []
    output_handles: list[str] = ["main"]
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: ExecuteWorkflowTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        items = input_items if input_items else [{}]

        # If schema fields are defined, format and coerce items matching the schema
        if params.input_data_mode == "fields" and params.schema_fields:
            formatted_items: list[dict[str, Any]] = []
            for item in items:
                new_item: dict[str, Any] = {}
                for field in params.schema_fields:
                    fname = field.name.strip()
                    if not fname:
                        continue
                    val = item.get(fname)
                    # Type casting helpers
                    if val is not None:
                        if field.type == "number":
                            try:
                                val = float(val) if "." in str(val) else int(val)
                            except (ValueError, TypeError):
                                pass
                        elif field.type == "boolean":
                            val = bool(val)
                        elif field.type == "string":
                            val = str(val)
                    new_item[fname] = val
                formatted_items.append(new_item if new_item else item)
            return NodeResult(output_items=formatted_items)

        return NodeResult(output_items=items)


# Aliases for compatibility
SubWorkflowTriggerNode = ExecuteWorkflowTriggerNode
NODE_REGISTRY["sub_workflow_trigger"] = ExecuteWorkflowTriggerNode
NODE_REGISTRY["when_executed_by_another_workflow"] = ExecuteWorkflowTriggerNode
