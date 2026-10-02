"""Schedule trigger node (spec 7, node #8, section 33).

Fires the workflow on a cron schedule. Supports multiple Trigger Rules (reference UI):
each rule is an independent schedule (seconds/minutes/hours/days/weeks/months/custom cron).
Single source: ScheduleTriggerParams.rules
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from croniter import croniter
from pydantic import BaseModel, Field, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


TriggerInterval = Literal["seconds", "minutes", "hours", "days", "weeks", "months", "cron"]


class TriggerRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    interval: TriggerInterval = "minutes"
    value: int | None = Field(default=5, ge=1, description="Interval value (1-59 for minutes/seconds etc.)")
    cron: str | None = Field(default=None, description="Cron expression for interval=cron")
    timezone: str = "UTC"
    collapsed: bool = False

    @model_validator(mode="after")
    def validate_rule(self):
        # Per-interval ranges
        if self.interval == "cron":
            if not self.cron or not croniter.is_valid(self.cron):
                raise ValueError(f"Invalid cron expression '{self.cron}'.")
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError:
                raise ValueError(f"Unknown timezone '{self.timezone}'.")
            return self
        # Non-cron: value required
        if self.value is None:
            raise ValueError(f"Value is required for interval '{self.interval}'.")
        ranges = {
            "seconds": (1, 59),
            "minutes": (1, 59),
            "hours": (1, 23),
            "days": (1, 31),
            "weeks": (1, 52),
            "months": (1, 12),
        }
        lo, hi = ranges[self.interval]
        if not (lo <= self.value <= hi):
            raise ValueError(f"Value for '{self.interval}' must be in range {lo}-{hi} (got {self.value}).")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Unknown timezone '{self.timezone}'.")
        return self

    def to_cron(self) -> str:
        """Convert interval+value to a 5-field cron expression.

        For seconds-based intervals, returns a placeholder cron that
        is NOT used for scheduling (seconds are handled with direct
        time math in the scheduler). The placeholder is for backwards
        compatibility and display purposes only.
        """
        if self.interval == "cron":
            return self.cron or "*/5 * * * *"
        if self.interval == "seconds":
            # Placeholder: seconds scheduling uses direct interval math
            return f"*/{self.value} * * * *"
        if self.interval == "minutes":
            return f"*/{self.value} * * * *"
        if self.interval == "hours":
            return f"0 */{self.value} * * *"
        if self.interval == "days":
            return f"0 0 */{self.value} * *"
        if self.interval == "weeks":
            return f"0 0 * * {(self.value or 0) % 7}"
        if self.interval == "months":
            return f"0 0 1 */{self.value} *"
        return "*/5 * * * *"


class ScheduleTriggerParams(BaseModel):
    # New multi-rule source of truth
    rules: list[TriggerRule] = Field(default_factory=lambda: [TriggerRule(interval="minutes", value=5, timezone="UTC")])
    # Legacy single cron for migration
    cron: str | None = Field(default=None, description="Legacy 5-field cron (migrated to rules).")
    timezone: str | None = Field(default=None, description="Legacy timezone (migrated).")

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_before(cls, data):
        if isinstance(data, dict):
            # If payload has legacy cron and no explicit rules, migrate
            cron_val = data.get("cron")
            if cron_val is not None and not data.get("rules"):
                if not cron_val:
                    raise ValueError("Cron expression must not be empty.")
                tz = data.get("timezone") or "UTC"
                try:
                    ZoneInfo(tz)
                except ZoneInfoNotFoundError:
                    raise ValueError(f"Unknown timezone '{tz}'.")
                if not croniter.is_valid(cron_val):
                    raise ValueError(f"Invalid cron expression '{cron_val}'.")
                data["rules"] = [{"id": "legacy", "interval": "cron", "cron": cron_val, "timezone": tz}]
                # Remove legacy fields so they don't confuse after-validators
                data.pop("cron", None)
                data.pop("timezone", None)
        return data

    @model_validator(mode="after")
    def validate_rules(self):
        if not self.rules:
            self.rules = [TriggerRule(interval="minutes", value=5, timezone="UTC")]
        for r in self.rules:
            if r.interval == "cron" and not r.cron:
                raise ValueError("Cron expression is required for Custom (Cron) interval.")
        # Validate legacy cron if present (should have been migrated, but just in case)
        if self.cron and not croniter.is_valid(self.cron):
            raise ValueError(f"Invalid cron expression '{self.cron}'.")
        return self


@register
class ScheduleTriggerNode(BaseNode[ScheduleTriggerParams]):
    node_type = "schedule"
    display_name = "Schedule Trigger"
    version = 1
    description = "Runs the workflow on a cron schedule."
    category = "Triggers"
    icon = "schedule"
    parameters_schema = ScheduleTriggerParams
    input_handles: list[str] = []

    async def run(
        self,
        ctx: NodeContext,
        params: ScheduleTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        # For manual Execute Step, return first rule's schedule; scheduler uses all rules
        rule = params.rules[0] if params.rules else TriggerRule()
        cron = rule.to_cron()
        tz = rule.timezone
        now = datetime.now(ZoneInfo(tz))

        # Standard human-readable output fields
        ordinal = lambda d: (
            f"{d}{'th' if 11 <= d <= 13 else {1:'st',2:'nd',3:'rd'}.get(d % 10, 'th')}"
        )
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        utc_offset = now.strftime("%z")
        utc_offset_fmt = f"UTC{utc_offset[:3]}:{utc_offset[3:]}" if utc_offset else "UTC"

        # Format readable date: "September 2nd 2026, 1:27:58 pm"
        hour_12 = now.hour % 12 or 12
        ampm = "am" if now.hour < 12 else "pm"
        readable_date = (
            f"{month_names[now.month - 1]} {ordinal(now.day)} {now.year}, "
            f"{hour_12}:{now.minute:02d}:{now.second:02d} {ampm}"
        )
        readable_time = f"{hour_12}:{now.minute:02d}:{now.second:02d} {ampm}"

        return NodeResult(
            output_items=[
                {
                    "success": True,
                    "timestamp": now.isoformat(),
                    "Readable date": readable_date,
                    "Readable time": readable_time,
                    "Day of week": day_names[now.weekday()],
                    "Year": str(now.year),
                    "Month": month_names[now.month - 1],
                    "Day of month": f"{now.day:02d}",
                    "Hour": str(now.hour),
                    "Minute": f"{now.minute:02d}",
                    "Second": f"{now.second:02d}",
                    "Timezone": f"{tz} ({utc_offset_fmt})",
                }
            ]
        )
