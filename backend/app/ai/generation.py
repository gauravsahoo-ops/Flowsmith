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
import re
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
    system = render_system_prompt(query=prompt)
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


def _clean_and_load_json(raw: str) -> Any:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except ValueError:
        # Strip trailing commas
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        return json.loads(cleaned)


def _parse_candidate(content: str) -> dict[str, Any] | None:
    """Parse the model output; tolerate reasoning tags, markdown fences, and commentary."""
    text = (content or "").strip()
    if not text:
        return None

    # Strip thinking/reasoning tags from models like DeepSeek-R1, Qwen, GLM
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    parsed: dict[str, Any] | None = None

    def _unwrap(cand: Any) -> dict[str, Any] | None:
        if not isinstance(cand, dict):
            return None
        if "workflow" in cand and isinstance(cand["workflow"], dict) and "nodes" in cand["workflow"]:
            cand = cand["workflow"]
        if "data" in cand and isinstance(cand["data"], dict) and "nodes" in cand["data"]:
            cand = cand["data"]
        # Convert nodes dict to list if needed
        if isinstance(cand.get("nodes"), dict):
            cand["nodes"] = list(cand["nodes"].values())
        if isinstance(cand.get("nodes"), list):
            return cand
        return None

    # 1. Try extracting from markdown code block ```json { ... } ``` or ``` { ... } ```
    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    if fence_match:
        try:
            cand = _clean_and_load_json(fence_match.group(1))
            cand = _unwrap(cand)
            if cand is not None:
                parsed = cand
        except ValueError:
            pass

    # 2. Try parsing whole text as JSON
    if parsed is None:
        try:
            cand = _clean_and_load_json(text)
            cand = _unwrap(cand)
            if cand is not None:
                parsed = cand
        except ValueError:
            pass

    # 3. Try outermost {...} block
    if parsed is None:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                cand = _clean_and_load_json(text[start:end + 1])
                cand = _unwrap(cand)
                if cand is not None:
                    parsed = cand
            except ValueError:
                pass

    # 4. Fallback: search for any block in text containing "nodes"
    if parsed is None:
        for m in re.finditer(r"(\{[\s\S]*?\})", text):
            cand_str = m.group(1)
            if '"nodes"' in cand_str:
                try:
                    cand = _clean_and_load_json(cand_str)
                    cand = _unwrap(cand)
                    if cand is not None:
                        parsed = cand
                        break
                except ValueError:
                    continue

    if not isinstance(parsed, dict) or not isinstance(parsed.get("nodes"), list):
        return None

    # Filter to valid dict nodes
    parsed["nodes"] = [n for n in parsed["nodes"] if isinstance(n, dict)]
    if not parsed["nodes"]:
        return None

    # Ensure all nodes have valid unique IDs
    seen_ids: set[str] = set()
    for idx, node in enumerate(parsed["nodes"]):
        nid = str(node.get("id") or "").strip()
        if not nid or nid in seen_ids:
            nid = f"node_{idx + 1}_{uuid.uuid4().hex[:6]}"
            node["id"] = nid
        seen_ids.add(nid)

    # Ensure at least one trigger node exists
    trigger_types = {"manual_trigger", "webhook", "schedule", "salesforce_trigger", "error_trigger", "chat_trigger", "form_trigger"}
    has_trigger = any(n.get("type") in trigger_types for n in parsed["nodes"])
    if not has_trigger:
        trig_type = "webhook" if "webhook" in text.lower() else ("schedule" if "schedule" in text.lower() or "every" in text.lower() else "manual_trigger")
        trig_id = f"trig_{uuid.uuid4().hex[:6]}"
        trig_node = {
            "id": trig_id,
            "type": trig_type,
            "position": {"x": 80, "y": 160},
            "parameters": {"path": f"hook-{uuid.uuid4().hex[:18]}"} if trig_type == "webhook" else {},
            "settings": {},
        }
        parsed["nodes"].insert(0, trig_node)

    for idx, node in enumerate(parsed["nodes"]):
        if "position" not in node or not isinstance(node["position"], dict):
            node["position"] = {"x": 80 + (idx * 280), "y": 160}
        if "parameters" not in node or not isinstance(node["parameters"], dict):
            node["parameters"] = {}
        if "settings" not in node or not isinstance(node["settings"], dict):
            node["settings"] = {}

        # Ensure trigger node paths meet the 24+ character security entropy
        ntype = str(node.get("type") or "")
        if ntype in ("webhook", "salesforce_trigger", "form_trigger", "chat_trigger"):
            params = node["parameters"]
            curr_path = str(params.get("path") or "")
            clean_prefix = re.sub(r"[^A-Za-z0-9_.-]", "", curr_path)[:12] or "hook"
            if len(curr_path) < 24:
                params["path"] = f"{clean_prefix}-{uuid.uuid4().hex[:18]}"

    # Validate and repair connections
    valid_ids = {n["id"] for n in parsed["nodes"]}
    type_to_id = {n["type"]: n["id"] for n in parsed["nodes"] if n.get("type")}
    raw_conns = parsed.get("connections")
    fixed_conns: list[dict[str, Any]] = []

    if isinstance(raw_conns, list):
        for c in raw_conns:
            if not isinstance(c, dict):
                continue
            src = c.get("source")
            tgt = c.get("target")
            if src not in valid_ids and src in type_to_id:
                src = type_to_id[src]
            if tgt not in valid_ids and tgt in type_to_id:
                tgt = type_to_id[tgt]
            if src in valid_ids and tgt in valid_ids and src != tgt:
                fixed_conns.append({**c, "source": src, "target": tgt})

    # If connections are empty or broke, chain sequentially
    if not fixed_conns and len(parsed["nodes"]) >= 2:
        for i in range(len(parsed["nodes"]) - 1):
            fixed_conns.append({
                "source": parsed["nodes"][i]["id"],
                "target": parsed["nodes"][i + 1]["id"],
            })

    parsed["connections"] = fixed_conns
    if not parsed.get("id"):
        parsed["id"] = f"wf_{uuid.uuid4().hex[:12]}"
    parsed.setdefault("name", "Generated workflow")
    parsed.setdefault("settings", {})
    parsed["status"] = "draft"  # never born active
    return parsed
