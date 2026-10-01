"""Intent Engine and Intelligent Clarification.

Extracts structured business intent from natural language prompts:
- Business goal
- Trigger specification
- Systems, connectors, and data sources
- Actions, conditions, loops, AI tasks
- Error policy, retries, and notifications
- Human approvals

Detects missing information and formulates targeted clarification questions
rather than guessing or hallucinating critical parameters.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Optional
from pydantic import BaseModel, Field

from app.ai.capabilities import CapabilityRegistry

ChatFn = Callable[..., Awaitable[dict[str, Any]]]


class ClarificationQuestion(BaseModel):
    id: str
    question: str
    parameter_key: str
    options: list[str] = Field(default_factory=list)
    impact: str = "Correctness of workflow configuration"
    allow_custom: bool = True


class ErrorPolicyIntent(BaseModel):
    retry_count: int = 0
    retry_attempts: int = 0
    backoff_strategy: str = "exponential"
    timeout_seconds: int = 300
    notify_on_failure: bool = False
    alert_channel: Optional[str] = None


class WorkflowIntent(BaseModel):
    goal: str
    mode: str = "build"  # build | modify | repair
    trigger: dict[str, Any] = Field(default_factory=dict)
    systems: list[str] = Field(default_factory=list)
    ai_tasks: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    loops: list[str] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    error_policy: ErrorPolicyIntent = Field(default_factory=ErrorPolicyIntent)
    notifications: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    missing_info: list[ClarificationQuestion] = Field(default_factory=list)
    summary: str = ""


class IntentEngine:
    """Extracts structured intent and computes necessary clarifications."""

    @classmethod
    async def extract_intent(
        cls,
        prompt: str,
        chat: Optional[ChatFn] = None,
        llm: Optional[dict[str, Any]] = None,
        existing_workflow: Optional[dict[str, Any]] = None,
        answers: Optional[dict[str, Any]] = None,
        mode: str = "build",
    ) -> WorkflowIntent:
        """Analyze user prompt against capability graph and extract structured intent."""
        if not chat or not llm:
            return cls._heuristic_intent(prompt, mode)

        reg = CapabilityRegistry.get_instance()
        caps = reg.search_capabilities(prompt, limit=10)

        nodes_summary = [f"{n['node_type']} ({n['display_name']}): {n['description'][:80]}" for n in caps["nodes"][:8]]
        conns_summary = [f"{c['connector_id']} ({c['display_name']}): ops={list(c['operations'].keys())[:6]}" for c in caps["connectors"][:8]]

        system_prompt = (
            "You are an enterprise workflow automation architect. Analyze the user request and extract "
            "a structured intent JSON object with EXACTLY this schema:\n"
            "{\n"
            '  "goal": "Brief description of the business outcome",\n'
            '  "mode": "build" | "modify" | "repair",\n'
            '  "trigger": {"type": "webhook|schedule|manual|event", "system": "...", "event": "..."},\n'
            '  "systems": ["Salesforce", "PostgreSQL", "Slack", ...],\n'
            '  "ai_tasks": ["Lead scoring", "Text classification", ...],\n'
            '  "conditions": ["score > 80", "status == active"],\n'
            '  "loops": ["iterate through customer records"],\n'
            '  "actions": [\n'
            '     {"id": "step_1", "system": "salesforce", "operation": "search_lead", "description": "..."}\n'
            '  ],\n'
            '  "error_policy": {"retry_count": 2, "backoff_strategy": "exponential", "notify_on_failure": true},\n'
            '  "notifications": [{"channel": "teams|slack|email", "recipient": "..."}],\n'
            '  "approvals": [{"role": "manager", "action": "..."}],\n'
            '  "missing_info": [\n'
            '     {"id": "q1", "question": "...", "parameter_key": "...", "options": ["opt1", "opt2"]}\n'
            '  ],\n'
            '  "summary": "1-2 sentence executive summary of the plan"\n'
            "}\n\n"
            "RULES:\n"
            "- Only ask clarification questions in 'missing_info' if CRITICAL information is truly unspecified\n"
            "  (e.g., condition threshold, specific notification channel).\n"
            "- If clarification answers are provided, incorporate them and do not re-ask those questions.\n"
            f"- Grounded capabilities:\nNodes: {', '.join(nodes_summary)}\nConnectors: {', '.join(conns_summary)}"
        )

        user_content = f"User Request: {prompt}\nTarget Mode: {mode}"
        if answers:
            user_content += f"\nClarification Answers: {json.dumps(answers, ensure_ascii=False)}"
        if existing_workflow and mode in ("modify", "repair"):
            user_content += f"\nExisting Workflow Context: {json.dumps(existing_workflow.get('name', 'Workflow'))} with {len(existing_workflow.get('nodes', []))} nodes"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            res = await chat(llm, messages, temperature=0.2, response_json=True, max_tokens=1500)
            raw = res.get("content") or "{}"
            raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
            fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw)
            if fence:
                raw = fence.group(1)
            parsed = json.loads(raw)
            return WorkflowIntent.model_validate(parsed)
        except Exception as e:
            # Fallback intent extraction if LLM formatting fails
            return cls._heuristic_intent(prompt, mode)

    @classmethod
    def _heuristic_intent(cls, prompt: str, mode: str) -> WorkflowIntent:
        """Deterministic heuristic fallback when LLM is unavailable or unparsable."""
        low = prompt.lower()
        systems = []
        if "salesforce" in low:
            systems.append("salesforce")
        if "slack" in low:
            systems.append("slack")
        if "teams" in low or "msteams" in low:
            systems.append("msteams")
        if "postgres" in low or "database" in low:
            systems.append("postgres")
        if "stripe" in low:
            systems.append("stripe")
        if "hubspot" in low:
            systems.append("hubspot")

        trigger_type = "webhook" if "webhook" in low else ("schedule" if ("every" in low or "daily" in low) else "manual")
        ai_tasks = ["AI Processing"] if ("ai" in low or "gpt" in low or "score" in low or "summarize" in low) else []
        retry_count = 2 if "retry" in low else 0

        return WorkflowIntent(
            goal=prompt[:100],
            mode=mode,
            trigger={"type": trigger_type, "system": systems[0] if systems else "manual"},
            systems=systems,
            ai_tasks=ai_tasks,
            conditions=["Condition route"] if ("if" in low or "check" in low) else [],
            loops=["Batch process"] if ("each" in low or "loop" in low) else [],
            error_policy=ErrorPolicyIntent(retry_count=retry_count, retry_attempts=retry_count, notify_on_failure="notify" in low),
            summary=f"Automate {prompt[:80]} with {', '.join(systems) if systems else 'flow logic'}",
        )
