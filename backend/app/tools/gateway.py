"""Tool Gateway: the only policy-enforced path to a tool side effect.

The gateway is intentionally independent of FastAPI and SQLAlchemy. It can be
used by the current agent node, by future orchestration services, and by tests.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import Any

from app.platform.contracts import (
    PolicyDecision,
    PolicyOutcome,
    RiskClass,
    ToolInvocation,
    ToolResult,
    ToolResultStatus,
)
from app.tools.registry import ToolRegistry

Runner = Callable[[Any, str, dict[str, Any]], Any]

APPROVAL_REQUIRED_RISKS = frozenset(
    {
        RiskClass.WRITE,
        RiskClass.DESTRUCTIVE,
        RiskClass.EXTERNAL_SIDE_EFFECT,
        RiskClass.FINANCIAL,
    }
)

RISK_TIERS: dict[RiskClass, int] = {
    RiskClass.READ_ONLY: 0,
    RiskClass.PII: 1,
    RiskClass.WRITE: 1,
    RiskClass.EXTERNAL_SIDE_EFFECT: 2,
    RiskClass.FINANCIAL: 3,
    RiskClass.DESTRUCTIVE: 3,
}


class ToolPolicyError(PermissionError):
    """Raised when a caller bypasses the gateway's authorization decision."""


class ToolGateway:
    """Authorize and invoke tools with capability + risk checks.

    ``runner`` is injectable for tests. The default runner delegates to the
    existing ``app.ai.tools.run_tool`` implementation, so migration can happen
    incrementally without duplicating tool handlers.
    """

    def __init__(self, registry: ToolRegistry, runner: Runner | None = None) -> None:
        self.registry = registry
        self._runner = runner

    @classmethod
    def from_native_tools(cls, runner: Runner | None = None) -> "ToolGateway":
        return cls(ToolRegistry.from_native_tools(), runner=runner)

    def authorize(
        self,
        tool_name: str,
        *,
        capabilities: frozenset[str],
        approval_granted: bool = False,
    ) -> PolicyDecision:
        descriptor = self.registry.get(tool_name)
        if descriptor is None:
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                reason_code="UNKNOWN_TOOL",
                evidence={"tool": tool_name},
            )

        required = f"tool:{tool_name}:invoke"
        if required not in capabilities and "tool:*:invoke" not in capabilities:
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                reason_code="CAPABILITY_MISSING",
                risk_tier=RISK_TIERS[descriptor.risk_class],
                evidence={"tool": tool_name, "required_capability": required},
            )

        tier = RISK_TIERS[descriptor.risk_class]
        if descriptor.risk_class in APPROVAL_REQUIRED_RISKS and not approval_granted:
            return PolicyDecision(
                outcome=PolicyOutcome.APPROVAL_REQUIRED,
                reason_code="RISK_TIER_REQUIRES_APPROVAL",
                risk_tier=tier,
                required_approvers=("workspace_approver",),
                quorum=2 if tier >= 3 else 1,
                expires_in_s=86_400,
                evidence={
                    "tool": tool_name,
                    "risk_class": descriptor.risk_class.value,
                    "idempotency": descriptor.idempotency.value,
                },
            )

        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            reason_code="POLICY_ALLOW",
            risk_tier=tier,
            evidence={"tool": tool_name, "risk_class": descriptor.risk_class.value},
        )

    async def invoke(
        self,
        invocation: ToolInvocation,
        *,
        capabilities: frozenset[str],
        approval_granted: bool = False,
    ) -> ToolResult:
        decision = self.authorize(
            invocation.tool_name,
            capabilities=capabilities,
            approval_granted=approval_granted,
        )
        if decision.outcome is PolicyOutcome.DENY:
            return ToolResult(
                tool_name=invocation.tool_name,
                status=ToolResultStatus.DENIED,
                error_code=decision.reason_code,
            )
        if decision.outcome is PolicyOutcome.APPROVAL_REQUIRED:
            return ToolResult(
                tool_name=invocation.tool_name,
                status=ToolResultStatus.APPROVAL_REQUIRED,
                error_code="APPROVAL_REQUIRED",
            )

        descriptor = self.registry.require(invocation.tool_name)
        started = time.perf_counter()
        try:
            result = await self._call_runner(invocation)
        except Exception as exc:  # noqa: BLE001 - gateway must normalize errors
            return ToolResult(
                tool_name=invocation.tool_name,
                status=ToolResultStatus.ERROR,
                error_code=type(exc).__name__,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        return ToolResult(
            tool_name=invocation.tool_name,
            status=ToolResultStatus.SUCCESS,
            output=result,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    async def _call_runner(self, invocation: ToolInvocation) -> Any:
        if self._runner is None:
            from app.ai.tools import run_tool

            result = run_tool(
                invocation.context,
                invocation.tool_name,
                dict(invocation.arguments),
            )
        else:
            result = self._runner(
                invocation.context,
                invocation.tool_name,
                dict(invocation.arguments),
            )
        if inspect.isawaitable(result):
            return await result
        return result
