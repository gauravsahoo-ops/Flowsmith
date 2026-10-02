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
    error_type: str = Field(
        default="errorMessage",
        description="Type of error to throw: 'errorMessage' or 'errorObject'.",
    )
    error_message: str = Field(
        default="An error occurred!",
        description="The error message to throw.",
    )
    error_object: Any = Field(
        default="",
        description="The custom error object to throw.",
    )


@register
class StopAndErrorNode(BaseNode[StopAndErrorParams]):
    node_type = "stop_and_error"
    display_name = "Stop and Error"
    version = 1
    description = "Throw an error in the workflow"
    category = "Flow"
    icon = "stop_and_error"
    parameters_schema = StopAndErrorParams
    input_handles = ["main"]
    output_handles = ["main"]

    async def run(
        self,
        ctx: NodeContext,
        params: StopAndErrorParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        error_type = params.error_type or "errorMessage"
        if error_type == "errorObject" and params.error_object:
            err_obj = params.error_object
            msg = str(err_obj) if not isinstance(err_obj, str) else err_obj
            details = {"error_object": err_obj, "input_items_count": len(input_items)}
        else:
            msg = params.error_message or "An error occurred!"
            details = {"input_items_count": len(input_items)}

        raise NodeExecutionError(
            message=msg,
            code="STOP_AND_ERROR",
            node_id=ctx.node_id,
            retryable=False,
            details=details,
        )
