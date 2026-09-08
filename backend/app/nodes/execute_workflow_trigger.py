"""Execute Workflow Trigger node (Flow / Triggers).

Starts the workflow when called by an Execute Sub-workflow node in another workflow.
Receives input items passed by the parent workflow and emits them to output.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register, NODE_REGISTRY


class ExecuteWorkflowTriggerParams(BaseModel):
    pass


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
        return NodeResult(output_items=items)


# Aliases for compatibility
SubWorkflowTriggerNode = ExecuteWorkflowTriggerNode
NODE_REGISTRY["sub_workflow_trigger"] = ExecuteWorkflowTriggerNode
NODE_REGISTRY["when_executed_by_another_workflow"] = ExecuteWorkflowTriggerNode
