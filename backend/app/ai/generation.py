"""NL → workflow generation service (Phase 15).

Pipeline: user prompt → planner (system prompt rendered from the LIVE
node/connector registries) → LLM candidate JSON → validate_candidate()
→ bounded repair loop (validation errors fed back, max 2 attempts)
→ {workflow, validation}.

The service NEVER persists anything. Creation is a separate, explicit
user action (approval gate); activation stays manual. The chat function
is injectable so evaluation tests run fully deterministically without
network or credentials.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Awaitable, Callable

from app.ai.catalog import render_system_prompt
from app.ai.validation import validate_candidate

ChatFn = Callable[..., Awaitable[dict[str, Any]]]

MAX_ATTEMPTS = 2
MAX_TOKENS = 3000


class GenerationError(Exception):
    """The model could not produce a valid candidate within the budget."""

    def __init__(self, message: str, validation: dict[str, Any] | None = None,
                 workflow: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.validation = validation or {"ok": False, "errors": [], "warnings": []}
        self.workflow = workflow


async def generate_workflow_spec(
    prompt: str,
    *,
    available_credentials: set[str],
    chat: ChatFn,
    llm: dict[str, Any],
    max_attempts: int = MAX_ATTEMPTS,
    existing_workflow: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Generate + validate one workflow candidate with optional memory and iteration context.

    Returns {"workflow": dict, "validation": {...}, "attempts": int}.
    Raises GenerationError (carrying the last validation report) when no
    valid candidate emerges within `max_attempts`.
    """
    system = render_system_prompt()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
    ]

    # Incorporate Copilot conversation history (turns)
    if history:
        for turn in history[-6:]:
            if isinstance(turn, dict) and turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": str(turn["content"])})

    user_prompt = f"USER REQUEST: {prompt}"
    if existing_workflow and isinstance(existing_workflow, dict) and existing_workflow.get("nodes"):
        user_prompt += (
            f"\n\nEXISTING WORKFLOW STATE TO MODIFY OR EXTEND:\n"
            f"{json.dumps(existing_workflow, ensure_ascii=False)}\n"
            f"Preserve existing valid nodes and wiring where applicable, modifying or adding nodes as requested."
        )

    messages.append({"role": "user", "content": user_prompt})

    last_workflow: dict[str, Any] | None = None
    last_validation: dict[str, Any] = {"ok": False, "errors": [], "warnings": []}

    for attempt in range(1, max_attempts + 1):
        message = await chat(llm, messages, temperature=0.3, response_json=True, max_tokens=MAX_TOKENS)
        candidate = _parse_candidate(message.get("content") or "")
        last_workflow = candidate
        if candidate is not None:
            last_validation = validate_candidate(candidate, available_credentials=available_credentials)
            if last_validation["ok"]:
                return {"workflow": candidate, "validation": last_validation, "attempts": attempt}
        else:
            last_validation = {
                "ok": False,
                "errors": [{"code": "NOT_JSON", "node_id": None, "field": None,
                            "message": "Model output was not a JSON object."}],
                "warnings": [],
            }

        # Bounded repair loop: show the model exactly what reality rejected.
        messages = messages + [
            {"role": "assistant", "content": json.dumps(last_workflow or {}, ensure_ascii=False)},
            {"role": "user", "content":
                "Your candidate was REJECTED by validation. Fix ONLY these issues and "
                "respond again with the full corrected JSON object:\n"
                + json.dumps(last_validation["errors"], ensure_ascii=False)},
        ]

    raise GenerationError(
        "The model could not produce a valid workflow from this request.",
        validation=last_validation, workflow=last_workflow,
    )


def _parse_candidate(content: str) -> dict[str, Any] | None:
    """Parse the model output; tolerate markdown fences; None when hopeless."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        # Last resort: grab the outermost {...} block.
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except ValueError:
            return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("nodes"), list):
        return None
    for idx, node in enumerate(parsed["nodes"]):
        if isinstance(node, dict):
            if "position" not in node or not isinstance(node["position"], dict):
                node["position"] = {"x": 80 + (idx * 280), "y": 160}
            if "parameters" not in node or not isinstance(node["parameters"], dict):
                node["parameters"] = {}
            if "settings" not in node or not isinstance(node["settings"], dict):
                node["settings"] = {}
    if not parsed.get("id"):
        parsed["id"] = f"wf_{uuid.uuid4().hex[:12]}"
    parsed.setdefault("name", "Generated workflow")
    parsed.setdefault("connections", [])
    parsed.setdefault("settings", {})
    parsed["status"] = "draft"  # never born active
    return parsed
