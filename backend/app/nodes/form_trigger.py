"""Form trigger node (Batch D, original implementation).

A public form starts the workflow. The node declares the form (title +
fields) and its public path; the API layer owns registration (same
`webhooks` table as plain webhooks, under the reserved `form/`
namespace — see `app.triggers.registry`) and submission delivery.

Downstream items look like:

    {"success": True, "form": {...validated fields...}, "query": {...}}
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register
from app.triggers.registry import FORM_TRIGGER_PREFIX

_PATH_RE = re.compile(r"^[A-Za-z0-9/_.\-]+$")

FieldType = Literal["text", "number", "boolean", "email"]


class FormField(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: FieldType = "text"
    required: bool = False
    label: str = ""


class FormTriggerParams(BaseModel):
    path: str = Field(min_length=1, description="Public path, e.g. 'form/contact-abcdefgh12345678'.")
    title: str = Field(default="Form", max_length=120)
    fields: list[FormField] = Field(default_factory=list, max_length=50)
    secret: str | None = Field(
        default=None,
        max_length=256,
        description="Optional submission token (Bearer/x-webhook-token/?token=); enforced when set.",
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.path.startswith(FORM_TRIGGER_PREFIX):
            raise ValueError(f"Form path must start with '{FORM_TRIGGER_PREFIX}'.")
        if not _PATH_RE.match(self.path):
            raise ValueError(f"Invalid form path '{self.path}'.")
        names = [f.name for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("Form field names must be unique.")


@register
class FormTriggerNode(BaseNode[FormTriggerParams]):
    node_type = "form_trigger"
    display_name = "Form Trigger"
    version = 1
    description = "Starts the workflow when someone submits its public form."
    category = "Triggers"
    icon = "form_trigger"
    parameters_schema = FormTriggerParams
    input_handles: list[str] = []

    async def run(
        self,
        ctx: NodeContext,
        params: FormTriggerParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if not input_items:
            return NodeResult(output_items=[{"success": True, "form": {}, "query": {}}])
        output_items: list[dict[str, Any]] = []
        for item in input_items:
            if isinstance(item, dict) and "form" in item:
                output_items.append({"success": True, **item})
            else:
                output_items.append({"success": True, "form": item, "query": {}})
        return NodeResult(output_items=output_items)
