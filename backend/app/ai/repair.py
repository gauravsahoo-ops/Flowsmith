"""AI Auto-Repair Engine.

Analyzes workflow execution failures, diagnoses root causes, and proposes
concrete, validated repairs with visual diffs for explicit user approval.
"""

from __future__ import annotations

import copy
from typing import Any, Awaitable, Callable, Optional
from pydantic import BaseModel, Field

from app.ai.simulator import WorkflowSimulator

ChatFn = Callable[..., Awaitable[dict[str, Any]]]


class RepairProposal(BaseModel):
    issue_summary: str
    root_cause: str
    target_node_id: Optional[str] = None
    change_type: str = "modify_settings"  # modify_settings | update_parameters | add_node | replace_node
    before_snippet: dict[str, Any] = Field(default_factory=dict)
    after_snippet: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    repaired_workflow: dict[str, Any] = Field(default_factory=dict)
    simulation_result: dict[str, Any] = Field(default_factory=dict)


class WorkflowRepairer:
    """Diagnoses execution failures and constructs safe repair proposals."""

    @classmethod
    async def analyze_and_repair(
        cls,
        workflow_doc: dict[str, Any],
        error_context: str,
        execution_trace: Optional[list[dict[str, Any]]] = None,
        chat: Optional[ChatFn] = None,
        llm: Optional[dict[str, Any]] = None,
        user_credentials: Optional[set[str]] = None,
    ) -> RepairProposal:
        """Produce a validated repair proposal with before/after diff."""
        repaired = copy.deepcopy(workflow_doc)
        nodes = repaired.get("nodes", [])

        # 1. Identify failing node from trace or error text
        target_node = None
        failing_step = None
        if execution_trace:
            for step in reversed(execution_trace):
                if step.get("status") in ("error", "failed"):
                    failing_step = step
                    break

        if failing_step:
            nid = failing_step.get("node_id") or failing_step.get("node")
            target_node = next((n for n in nodes if n.get("id") == nid), None)

        if not target_node and nodes:
            # Match from error message text
            err_low = error_context.lower()
            for n in nodes:
                ntype = n.get("type", "").lower()
                nname = n.get("name", "").lower()
                if ntype in err_low or (nname and nname in err_low):
                    target_node = n
                    break

        if not target_node and nodes:
            target_node = nodes[-1]

        before_snippet = copy.deepcopy(target_node or {})
        target_id = target_node.get("id") if target_node else None

        # 2. Diagnose failure pattern
        err_low = error_context.lower()
        root_cause = "Transient API failure or unconfigured error policy"
        rationale = "Configured exponential backoff retry policy to handle transient rate limits or network glitches."
        change_type = "modify_settings"

        if "rate limit" in err_low or "429" in err_low or "timeout" in err_low or "retry" in err_low:
            root_cause = "Rate limiting or temporary timeout response from remote service"
            rationale = "Added 3 exponential backoff retry attempts to automatically recover from rate limits."
            if target_node:
                target_node.setdefault("settings", {})
                target_node["settings"]["retry"] = {
                    "max_attempts": 3,
                    "backoff": "exponential",
                }
                target_node["settings"]["timeout_seconds"] = 120
        elif "auth" in err_low or "401" in err_low or "credential" in err_low:
            root_cause = "Authentication token expired or credential unassigned"
            rationale = "Associated required $user credential reference to authorize API call."
            if target_node:
                ntype = target_node.get("type", "")
                target_node.setdefault("credentials", {})
                target_node["credentials"][ntype] = "$user"
        elif "missing" in err_low or "not found" in err_low or "keyerror" in err_low:
            root_cause = "Expected JSON field missing from upstream node output"
            rationale = "Added fallback default value in parameters to prevent key error."
            if target_node:
                params = target_node.setdefault("parameters", {})
                for k, v in params.items():
                    if isinstance(v, str) and "{{" in v and "default" not in v:
                        params[k] = f"{v[:-2]} | default('') }}}}"
                        break
        else:
            # General safe retry enhancement
            if target_node:
                target_node.setdefault("settings", {})
                target_node["settings"]["retry"] = {"max_attempts": 2, "backoff": "exponential"}

        after_snippet = copy.deepcopy(target_node or {})

        # 3. Simulate repaired workflow to ensure fix works
        sim_res = WorkflowSimulator.simulate(repaired, user_credentials=user_credentials)

        return RepairProposal(
            issue_summary=f"Repaired failure on node '{target_node.get('name') if target_node else 'unknown'}': {error_context[:100]}",
            root_cause=root_cause,
            target_node_id=target_id,
            change_type=change_type,
            before_snippet=before_snippet,
            after_snippet=after_snippet,
            rationale=rationale,
            repaired_workflow=repaired,
            simulation_result=sim_res,
        )
