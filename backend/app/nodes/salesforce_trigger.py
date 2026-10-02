"""Salesforce event trigger node (Phase 10).

Receives Salesforce **Outbound Messages**: a Workflow Rule (or Flow
with an outbound-message action) POSTs a SOAP envelope to this
workflow's public URL whenever records change. Salesforce retries for
24 hours until the endpoint ACKs, so delivery is at-least-once and
deduplication happens server-side by MessageId.

This is the only reliably supportable push mechanism without a
persistent subscriber: Change Data Capture and Platform Events require
a long-lived CometD/Bayeux connection with OAuth token lifecycle and
replay management, which this codebase intentionally does not
hand-roll. Generic Flow→HTTP callouts can already use the plain
webhook trigger with JSON bodies.

The path is namespaced under ``sf-outbound/`` so it cannot collide
with generic webhook paths; registration in the webhooks table and the
public endpoint wiring are handled by the API layer (mirroring the
webhook trigger). The node itself only declares/validates parameters
and passes parsed events through as items.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

#: Reserved namespace shared with the public endpoint + trigger sync.
SALESFORCE_TRIGGER_PREFIX = "sf-outbound/"
_PATH_RE = re.compile(r"^sf-outbound/[A-Za-z0-9_-]{6,64}$")


class SalesforceTriggerParams(BaseModel):
    path: str = Field(
        description=(
            "URL suffix under /api/triggers/salesforce/outbound/, e.g. "
            "'sf-outbound/lead-create-9f2ac1'. Treat the suffix like a "
            "secret: anyone who knows it can post events."
        ),
    )
    object_name: str = Field(
        default="",
        description=(
            "Optional object filter (e.g. Lead). Notifications for other "
            "objects are ACKed but not executed."
        ),
    )
    description: str = Field(default="", description="What fires this trigger (internal note).")

    def model_post_init(self, __context: Any) -> None:
        if not _PATH_RE.match(self.path):
            raise ValueError(
                "Invalid salesforce_trigger path "
                f"'{self.path}': must match sf-outbound/<6-64 letters/digits/-/_>."
            )


@register
class SalesforceTriggerNode(BaseNode[SalesforceTriggerParams]):
    node_type = "salesforce_trigger"
    display_name = "Salesforce Event Trigger"
    version = 1
    description = "Starts the workflow when Salesforce sends an Outbound Message (record create/update)."
    category = "Triggers"
    icon = "salesforce"
    parameters_schema = SalesforceTriggerParams
    input_handles: list[str] = []

    async def run(
        self,
        ctx: NodeContext,
        params: SalesforceTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        """Pass through the API layer's parsed notification items.

        Each item looks like::

            {
              "object_type": "Lead",
              "record": {"Id": "...", "Email": ...},
              "record_id": "00Q...",
              "organization_id": "00D...",
              "action_id": "...",
              "message_id": "04l...",
              "notification_id": "04t...",
            }
        """
        if not input_items:
            return NodeResult(output_items=[{
                "success": True,
                "object_type": "", "record": {}, "record_id": "",
                "organization_id": "", "action_id": "",
                "message_id": "", "notification_id": "",
            }])
        return NodeResult(
            output_items=[{"success": True, **item} for item in input_items if isinstance(item, dict)]
        )
