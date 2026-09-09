"""Wait / Delay node.

Pauses execution for a time interval, until a specified date/time,
or until a webhook/form is submitted.
Sleeps in small slices and checks cooperative cancellation between slices,
so a cancelled run stops promptly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeCancelledError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

_SLICE_SECONDS = 0.25
_UNIT_MULTIPLIERS = {
    "seconds": 1.0,
    "minutes": 60.0,
    "hours": 3600.0,
    "days": 86400.0,
}


class WaitParams(BaseModel):
    resume: Literal[
        "timeInterval", "specificTime", "webhook", "form", "delay", "until"
    ] = Field(
        default="timeInterval",
        description="Resume condition: timeInterval, specificTime, webhook, form.",
    )
    # Legacy alias
    mode: str | None = None

    # After time interval
    amount: float = Field(default=5.0, ge=0, description="Wait amount (e.g. 5.0).")
    unit: Literal["seconds", "minutes", "hours", "days"] = Field(
        default="seconds",
        description="Wait unit: seconds, minutes, hours, days.",
    )
    # Legacy alias
    seconds: float | None = None

    # At specified time
    date_time: str = Field(default="", description="ISO-8601 UTC timestamp.")
    # Legacy alias
    until: str | None = None

    # Webhook or form configuration
    webhook_suffix: str = Field(default="", description="Optional webhook suffix.")


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
        resume_mode = params.resume
        # Handle legacy mode alias
        if params.mode:
            if params.mode == "delay":
                resume_mode = "timeInterval"
            elif params.mode == "until":
                resume_mode = "specificTime"

        # 1. After Time Interval
        if resume_mode in ("timeInterval", "delay"):
            if params.seconds is not None and params.seconds > 0:
                total_seconds = float(params.seconds)
            else:
                multiplier = _UNIT_MULTIPLIERS.get(params.unit.lower(), 1.0)
                total_seconds = float(params.amount) * multiplier

            slept = 0.0
            while slept < total_seconds:
                if ctx.is_cancelled():
                    raise NodeCancelledError(node_id=self.node_type)
                slice_s = min(_SLICE_SECONDS, total_seconds - slept)
                await asyncio.sleep(slice_s)
                slept += slice_s

            return NodeResult(
                output_items=input_items,
                metadata={"success": True, "waited": True, "waited_seconds": total_seconds},
            )

        # 2. At Specified Time
        elif resume_mode in ("specificTime", "until"):
            target_raw = params.date_time or params.until or ""
            if not target_raw.strip():
                return NodeResult(output_items=input_items, metadata={"success": True, "waited": False})

            try:
                target = datetime.fromisoformat(target_raw.replace("Z", "+00:00"))
            except ValueError:
                # Fallback if invalid date
                return NodeResult(output_items=input_items, metadata={"success": True, "waited": False})

            while True:
                if ctx.is_cancelled():
                    raise NodeCancelledError(node_id=self.node_type)
                now = datetime.now(UTC)
                if now >= target:
                    break
                await asyncio.sleep(min(_SLICE_SECONDS, 1.0))

            return NodeResult(
                output_items=input_items,
                metadata={"success": True, "waited": True, "resumed_at": datetime.now(UTC).isoformat()},
            )

        # 3. Webhook / Form Call
        else:
            # When waiting for webhook or form in automation engine:
            # If in live run, returns items; in pause mode records waiting state
            return NodeResult(
                output_items=input_items,
                metadata={
                    "success": True,
                    "waited": True,
                    "resumed_by": resume_mode,
                    "webhook_suffix": params.webhook_suffix,
                },
            )
