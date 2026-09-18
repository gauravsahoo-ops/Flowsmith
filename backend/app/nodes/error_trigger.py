"""Error Trigger node: triggers when another workflow encounters an unhandled execution error."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class ErrorTriggerParams(BaseModel):
    pass


@register
class ErrorTriggerNode(BaseNode[ErrorTriggerParams]):
    node_type = "error_trigger"
    display_name = "Error Trigger"
    version = 1
    description = "Triggers automatically when a linked workflow encounters an execution failure."
    category = "Triggers"
    icon = "alert_triangle"
    parameters_schema = ErrorTriggerParams
    input_handles: list[str] = []

    async def run(
        self,
        ctx: NodeContext,
        params: ErrorTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        # If triggered by the engine's error workflow handler, use the incoming items.
        # Otherwise (e.g. manual canvas test run), supply mock failure data.
        items = input_items if input_items else [{
            "error": {
                "message": "Sample execution failure for canvas testing",
                "code": "EXECUTION_FAILED",
                "node_id": "http_request_1",
            },
            "failed_execution_id": "exec_sample_test",
            "failed_workflow_id": "wf_sample_source",
        }]
        return NodeResult(output_items=items)
