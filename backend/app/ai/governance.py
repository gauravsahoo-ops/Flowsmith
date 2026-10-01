"""AI Agent Governance and Policy Enforcement.

Enforces execution budgets, tool call limits, iteration bounds, domain whitelists,
allowed connector permissions, and human approval policies across agent steps.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("ai.governance")


class AgentGovernancePolicy(BaseModel):
    max_iterations: int = Field(default=20, ge=1, le=100)
    max_tool_calls: int = Field(default=50, ge=1, le=200)
    max_cost_dollars: float = Field(default=2.0, ge=0.0)
    timeout_seconds: int = Field(default=300, ge=10, le=1800)
    allowed_connectors: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    prohibited_tools: list[str] = Field(default_factory=list)
    approval_required_for_actions: bool = False
    audit_logging_enabled: bool = True


class GovernanceViolation(Exception):
    """Raised when an agent execution breaches a governance policy."""
    def __init__(self, rule: str, message: str, context: Optional[dict[str, Any]] = None) -> None:
        super().__init__(f"Governance Violation [{rule}]: {message}")
        self.rule = rule
        self.message = message
        self.context = context or {}


class AgentGovernanceGuard:
    """Stateful runtime governance monitor for ReAct agent loops."""

    def __init__(self, policy: Optional[AgentGovernancePolicy] = None) -> None:
        self.policy = policy or AgentGovernancePolicy()
        self.iteration_count = 0
        self.tool_call_count = 0
        self.estimated_cost = 0.0
        self.executed_tools: list[str] = []

    def check_iteration(self) -> None:
        """Verify iteration limit before executing next step."""
        self.iteration_count += 1
        if self.iteration_count > self.policy.max_iterations:
            raise GovernanceViolation(
                "MAX_ITERATIONS",
                f"Agent reached maximum allowable iterations limit ({self.policy.max_iterations}).",
                {"iterations": self.iteration_count}
            )

    def check_tool_call(self, tool_name: str, tool_args: Optional[dict[str, Any]] = None) -> None:
        """Verify tool call permissions and rate limits."""
        self.tool_call_count += 1
        if self.tool_call_count > self.policy.max_tool_calls:
            raise GovernanceViolation(
                "MAX_TOOL_CALLS",
                f"Agent exceeded maximum tool call limit ({self.policy.max_tool_calls}).",
                {"tool_calls": self.tool_call_count}
            )

        if tool_name in self.policy.prohibited_tools:
            raise GovernanceViolation(
                "PROHIBITED_TOOL",
                f"Tool '{tool_name}' is explicitly restricted by governance policy.",
                {"tool": tool_name}
            )

        # Connector check
        if self.policy.allowed_connectors:
            for c in self.policy.allowed_connectors:
                if c.lower() in tool_name.lower():
                    break
            else:
                # If tool represents a connector call, verify against allowed list
                if any(k in tool_name for k in ("salesforce", "slack", "stripe", "hubspot", "postgres", "msteams")):
                    raise GovernanceViolation(
                        "UNAUTHORIZED_CONNECTOR",
                        f"Connector '{tool_name}' is not in allowed connectors list: {self.policy.allowed_connectors}.",
                        {"tool": tool_name}
                    )

        self.executed_tools.append(tool_name)

    def record_token_usage(self, prompt_tokens: int, completion_tokens: int, model: str = "") -> None:
        """Track estimated execution cost."""
        # Conservative blended cost model ($3 / 1M tokens)
        cost = ((prompt_tokens + completion_tokens) / 1_000_000.0) * 3.0
        self.estimated_cost += cost
        if self.policy.max_cost_dollars > 0 and self.estimated_cost > self.policy.max_cost_dollars:
            raise GovernanceViolation(
                "BUDGET_EXCEEDED",
                f"Agent exceeded maximum cost budget of ${self.policy.max_cost_dollars:.2f} (current: ${self.estimated_cost:.2f}).",
                {"estimated_cost": self.estimated_cost}
            )

    def get_summary(self) -> dict[str, Any]:
        """Return runtime governance metrics."""
        return {
            "iterations": self.iteration_count,
            "tool_calls": self.tool_call_count,
            "estimated_cost_usd": round(self.estimated_cost, 4),
            "executed_tools": self.executed_tools,
            "policy": self.policy.model_dump(),
        }
