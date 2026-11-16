"""Agent runtime helpers.

The first extracted boundary is tool execution: the `ai_agent` node delegates
tool calls here, and the policy gateway can be enabled without duplicating the
existing `run_tool` handlers. When the gateway requires approval, the agent
preflights the batch and pauses durably instead of feeding a pending string back
to the model.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.platform.contracts import (
    PolicyOutcome,
    RiskClass,
    ToolInvocation,
    ToolResult,
    ToolResultStatus,
)
from app.tools.gateway import RISK_TIERS, ToolGateway

_GATEWAY: ToolGateway | None = None


class ToolApprovalRequired(PermissionError):
    """A gated tool call must pause the run for a durable human decision.

    The agent runtime catches this before the tool executes, persists the ReAct
    state, and resumes only after an approval decision. It deliberately carries
    enough metadata for the approval record (risk, quorum, expiry) without
    exposing secret argument values to callers.
    """

    def __init__(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        risk_class: str = RiskClass.WRITE.value,
        risk_tier: int = 1,
        quorum: int = 1,
        expires_in_s: int = 86_400,
        reason_code: str = "APPROVAL_REQUIRED",
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.arguments = dict(arguments)
        self.risk_class = risk_class
        self.risk_tier = max(1, int(risk_tier))
        self.quorum = max(1, int(quorum))
        self.expires_in_s = max(1, int(expires_in_s))
        self.reason_code = reason_code
        self.evidence = dict(evidence or {})
        super().__init__(f"Tool '{tool_name}' requires human approval.")


def _get_gateway() -> ToolGateway:
    global _GATEWAY
    if _GATEWAY is None:
        _GATEWAY = ToolGateway.from_native_tools()
    return _GATEWAY


def _policy_enabled(policy_enabled: bool | None) -> bool:
    return (
        get_settings().agent_tool_policy_enabled
        if policy_enabled is None
        else policy_enabled
    )


def _capabilities(tool_name: str, declared_tools: list[str] | None) -> frozenset[str]:
    allowed = declared_tools or [tool_name]
    return frozenset(f"tool:{name}:invoke" for name in allowed)


def preflight_tool_call(
    ctx: Any,
    tool_name: str,
    args: dict[str, Any],
    *,
    declared_tools: list[str] | None = None,
    gateway: ToolGateway | None = None,
    policy_enabled: bool | None = None,
) -> None:
    """Raise :class:`ToolApprovalRequired` before a gated tool executes.

    This is intentionally a pure authorization check: it never runs the tool
    and therefore cannot produce a partial side effect. The agent preflights a
    whole tool-call batch so a pause happens before any call in that batch runs.
    """
    if not _policy_enabled(policy_enabled):
        return

    active_gateway = gateway or _get_gateway()
    decision = active_gateway.authorize(
        tool_name,
        capabilities=_capabilities(tool_name, declared_tools),
    )
    if decision.outcome is not PolicyOutcome.APPROVAL_REQUIRED:
        return

    descriptor = active_gateway.registry.get(tool_name)
    risk_class = (
        descriptor.risk_class.value
        if descriptor is not None
        else str(decision.evidence.get("risk_class") or RiskClass.WRITE.value)
    )
    risk_tier = decision.risk_tier or RISK_TIERS.get(
        descriptor.risk_class if descriptor is not None else RiskClass.WRITE, 1
    )
    raise ToolApprovalRequired(
        tool_name,
        args,
        risk_class=risk_class,
        risk_tier=risk_tier,
        quorum=max(1, decision.quorum or (2 if risk_tier >= 3 else 1)),
        expires_in_s=decision.expires_in_s or 86_400,
        reason_code=decision.reason_code,
        evidence=dict(decision.evidence),
    )


def _result_message(result: ToolResult, tool_name: str, args: dict[str, Any]) -> str:
    if result.status is ToolResultStatus.SUCCESS:
        output = result.output
        return output if isinstance(output, str) else json.dumps(output, default=str)
    if result.status is ToolResultStatus.APPROVAL_REQUIRED:
        return json.dumps(
            {
                "status": "pending_approval",
                "tool": tool_name,
                "arguments": args,
                "message": (
                    f"Tool '{tool_name}' requires human approval before it can "
                    "execute. The action was not performed."
                ),
            }
        )
    if result.status is ToolResultStatus.DENIED:
        return json.dumps(
            {
                "status": "denied",
                "tool": tool_name,
                "code": result.error_code or "POLICY_DENIED",
                "message": "The run is not authorized to invoke this tool.",
            }
        )
    return json.dumps(
        {
            "status": "error",
            "tool": tool_name,
            "code": result.error_code or "TOOL_ERROR",
            "message": "The tool failed before producing a result.",
        }
    )


async def execute_tool(
    ctx: Any,
    tool_name: str,
    args: dict[str, Any],
    *,
    declared_tools: list[str] | None = None,
    gateway: ToolGateway | None = None,
    policy_enabled: bool | None = None,
    raise_on_approval: bool = False,
    approval_granted: bool = False,
) -> str:
    """Execute one agent tool call.

    The default path is the existing ``run_tool`` implementation. When the
    Phase 3 flag is enabled, all calls pass through the Tool Gateway, which
    enforces capabilities and blocks write/destructive tools until the agent
    pauses for a durable approval decision.

    ``raise_on_approval`` lets the agent runtime pause durably instead of
    feeding a "pending approval" observation back to the model.
    """
    enabled = _policy_enabled(policy_enabled)
    if not enabled:
        from app.ai.tools import run_tool

        return await run_tool(ctx, tool_name, args)

    run_id = str(getattr(ctx, "execution_id", None) or "run")
    node_id = str(getattr(ctx, "node_id", None) or "agent")
    invocation = ToolInvocation(
        run_id=run_id,
        node_id=node_id,
        tool_name=tool_name,
        arguments=args,
        idempotency_key=f"{run_id}:{node_id}:{tool_name}:0",
        context=ctx,
    )
    active_gateway = gateway or _get_gateway()
    result = await active_gateway.invoke(
        invocation,
        capabilities=_capabilities(tool_name, declared_tools),
        approval_granted=approval_granted,
    )
    if result.status is ToolResultStatus.APPROVAL_REQUIRED and raise_on_approval:
        descriptor = getattr(active_gateway, "registry", None)
        descriptor = descriptor.get(tool_name) if descriptor is not None else None
        risk_class = (
            descriptor.risk_class if descriptor is not None else RiskClass.WRITE
        )
        risk_tier = RISK_TIERS.get(risk_class, 1)
        raise ToolApprovalRequired(
            tool_name,
            args,
            risk_class=risk_class.value,
            risk_tier=risk_tier,
            quorum=2 if risk_tier >= 3 else 1,
            reason_code=result.error_code or "APPROVAL_REQUIRED",
        )
    return _result_message(result, tool_name, args)
