"""Stop and Error node (Flow).

Throws an explicit error during workflow execution, immediately halting the run
or triggering an error workflow if configured.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class StopAndErrorParams(BaseModel):
    error_message: str = Field(
        default="An error occurred in the workflow.",
        description="The error message to throw.",
    )
    error_type: str = Field(
        default="WorkflowError",
        description="Type or category of the error.",
    )


@register
class StopAndErrorNode(BaseNode[StopAndErrorParams]):
    node_type = "stop_and_error"
    display_name = "Stop and Error"
    version = 1
    description = "Throw an error in the workflow"
    category = "Flow"
    icon = "🚫"
    parameters_schema = StopAndErrorParams
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(
        self,
        ctx: NodeContext,
        params: StopAndErrorParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        msg = params.error_message or "An error occurred in the workflow."
        raise NodeExecutionError(
            message=msg,
            code=params.error_type or "STOP_AND_ERROR",
            node_id=ctx.node_id,
            retryable=False,
            details={"input_items_count": len(input_items)},
        )
