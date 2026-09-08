"""Wait / Delay node (Phase 43).

Pauses execution for a fixed number of seconds (or until an absolute
ISO-8601 timestamp). Sleeps in small slices and checks cooperative
cancellation between slices, so a cancelled run stops promptly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.engine.errors import NodeCancelledError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

_SLICE_SECONDS = 0.25


class WaitParams(BaseModel):
    mode: Literal["delay", "until"] = "delay"
    seconds: float = Field(default=5.0, ge=0, le=3600, description="Delay seconds (mode=delay).")
    until: str = Field(default="", description="ISO-8601 UTC timestamp (mode=until).")

    @model_validator(mode="after")
    def _validate(self) -> "WaitParams":
        if self.mode == "until":
            if not self.until.strip():
                raise ValueError("mode=until requires an ISO-8601 'until' timestamp.")
            try:
                datetime.fromisoformat(self.until.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"'until' is not a valid ISO-8601 timestamp: {exc}") from exc
        return self


@register
class WaitNode(BaseNode[WaitParams]):
    node_type = "wait"
    display_name = "Wait"
    version = 1
    description = "Wait before continue with execution"
    category = "Flow"
    icon = "wait"
    parameters_schema = WaitParams

    async def run(
        self,
        ctx: NodeContext,
        params: WaitParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        target = (
            datetime.fromisoformat(params.until.replace("Z", "+00:00"))
            if params.mode == "until"
            else None
        )
        while True:
            if ctx.is_cancelled():
                raise NodeCancelledError(node_id=self.node_type)
            if params.mode == "delay":
                remaining = params.seconds
                slept = 0.0
                while slept < remaining:
                    if ctx.is_cancelled():
                        raise NodeCancelledError(node_id=self.node_type)
                    slice_s = min(_SLICE_SECONDS, remaining - slept)
                    await asyncio.sleep(slice_s)
                    slept += slice_s
                break
            # mode == until
            now = datetime.now(UTC)
            if target is not None and now >= target:
                break
            await asyncio.sleep(min(_SLICE_SECONDS, 1.0))

        return NodeResult(
            output_items=input_items,
            metadata={"success": True, "waited": True},
        )
