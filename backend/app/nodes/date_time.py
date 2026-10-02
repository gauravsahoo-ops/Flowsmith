"""Date/time node.

Local date/time helpers without external calls: current time, format,
parse, shift, and diff. All outputs are plain items so downstream
expressions can use them directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class DateTimeParams(BaseModel):
    operation: Literal["now", "format", "parse", "shift", "diff"] = Field(
        default="now", description="now | format | parse | shift | diff"
    )
    # format/parse
    value: str = Field(default="", description="Input datetime string for format/parse/diff end.")
    input_format: str = Field(default="%Y-%m-%dT%H:%M:%S", description="strptime format for parse.")
    output_format: str = Field(default="%Y-%m-%dT%H:%M:%S", description="strftime format for output.")
    # shift
    days: float = Field(default=0, ge=-36500, le=36500)
    hours: float = Field(default=0, ge=-876000, le=876000)
    minutes: float = Field(default=0, ge=-52560000, le=52560000)
    base: str = Field(default="", description="Base datetime for shift (empty = now).")
    # diff
    start: str = Field(default="", description="Start datetime for diff.")
    unit: Literal["seconds", "minutes", "hours", "days"] = Field(default="seconds")
    timezone: str = Field(default="UTC", description="IANA timezone, e.g. UTC or Asia/Kolkata.")


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _parse_flexible(raw: str, fmt: str, tz: ZoneInfo) -> datetime:
    raw = (raw or "").strip()
    if not raw:
        return datetime.now(tz)
    # Try explicit format first, then ISO.
    try:
        dt = datetime.strptime(raw, fmt)
        return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
    except Exception as exc:
        raise NodeExecutionError(
            f"Could not parse datetime {raw!r}.",
            code="DATETIME_PARSE_ERROR",
            node_id="date_time",
            retryable=False,
        ) from exc


@register
class DateTimeNode(BaseNode[DateTimeParams]):
    node_type = "date_time"
    display_name = "Date & Time"
    version = 1
    description = "Now, format, parse, shift, and diff datetimes."
    category = "Transform"
    icon = "date_time"
    parameters_schema = DateTimeParams

    async def run(
        self,
        ctx: NodeContext,
        params: DateTimeParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        tz = _tz(params.timezone)
        now = datetime.now(tz)
        if params.operation == "now":
            return NodeResult(output_items=[{"now": now.strftime(params.output_format), "timezone": params.timezone}])
        if params.operation == "format":
            dt = _parse_flexible(params.value, params.input_format, tz)
            return NodeResult(output_items=[{"formatted": dt.strftime(params.output_format)}])
        if params.operation == "parse":
            dt = _parse_flexible(params.value, params.input_format, tz)
            return NodeResult(output_items=[{"iso": dt.isoformat(), "epoch": int(dt.timestamp())}])
        if params.operation == "shift":
            base = _parse_flexible(params.base, params.input_format, tz) if params.base else now
            shifted = base + timedelta(days=params.days, hours=params.hours, minutes=params.minutes)
            return NodeResult(output_items=[{"shifted": shifted.strftime(params.output_format)}])
        # diff
        end = _parse_flexible(params.value, params.input_format, tz)
        start = _parse_flexible(params.start, params.input_format, tz)
        seconds = (end - start).total_seconds()
        factor = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}[params.unit]
        return NodeResult(output_items=[{"diff": seconds / factor, "unit": params.unit}])
