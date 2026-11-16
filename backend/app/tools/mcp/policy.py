"""MCP tool policy and descriptor generation.

Pure functions: no network I/O and no database access. The registry supplies
the server record; the Tool Gateway supplies the risk/approval context.
"""

from __future__ import annotations

import re
from typing import Any

from app.models import MCPServer
from app.platform.contracts import (
    Idempotency,
    PolicyDecision,
    PolicyOutcome,
    RiskClass,
    ToolDescriptor,
)
from app.tools.gateway import APPROVAL_REQUIRED_RISKS, RISK_TIERS

_NAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _tool_name(value: str) -> str:
    return _NAME_SAFE.sub("_", str(value or "").strip())[:128] or "tool"


def evaluate_tool_policy(
    server: MCPServer,
    tool_name: str,
    *,
    risk_class: RiskClass = RiskClass.WRITE,
    approval_granted: bool = False,
) -> PolicyDecision:
    """Return allow/deny/approval for one MCP tool invocation.

    Untrusted servers never auto-run write-capable tools. An empty
    ``allowed_tools`` list means "no allowlist configured", not "allow all":
    the trust/risk checks below still apply.
    """
    name = str(tool_name or "").strip()
    if not name:
        return PolicyDecision(
            outcome=PolicyOutcome.DENY,
            reason_code="MCP_TOOL_NAME_REQUIRED",
        )
    if not server.enabled:
        return PolicyDecision(
            outcome=PolicyOutcome.DENY,
            reason_code="MCP_SERVER_DISABLED",
            evidence={"server_id": server.id},
        )

    denied = set(server.denied_tools or [])
    allowed = set(server.allowed_tools or [])
    if name in denied:
        return PolicyDecision(
            outcome=PolicyOutcome.DENY,
            reason_code="MCP_TOOL_DENIED",
            evidence={"server_id": server.id, "tool": name},
        )
    if allowed and name not in allowed:
        return PolicyDecision(
            outcome=PolicyOutcome.DENY,
            reason_code="MCP_TOOL_NOT_ALLOWED",
            evidence={"server_id": server.id, "tool": name},
        )

    tier = RISK_TIERS.get(risk_class, 1)
    untrusted = server.trust_level != "verified"
    needs_approval = untrusted or risk_class in APPROVAL_REQUIRED_RISKS
    if needs_approval and not approval_granted:
        return PolicyDecision(
            outcome=PolicyOutcome.APPROVAL_REQUIRED,
            reason_code=(
                "MCP_UNTRUSTED_SERVER" if untrusted else "MCP_RISK_TIER_REQUIRES_APPROVAL"
            ),
            risk_tier=tier,
            required_approvers=("workspace_approver",),
            quorum=2 if tier >= 3 else 1,
            expires_in_s=86_400,
            evidence={
                "server_id": server.id,
                "tool": name,
                "trust_level": server.trust_level,
                "risk_class": risk_class.value,
            },
        )

    return PolicyDecision(
        outcome=PolicyOutcome.ALLOW,
        reason_code="MCP_POLICY_ALLOW",
        risk_tier=tier,
        evidence={
            "server_id": server.id,
            "tool": name,
            "trust_level": server.trust_level,
            "risk_class": risk_class.value,
        },
    )


def descriptor_from_tool(
    server: MCPServer,
    tool: dict[str, Any],
    *,
    risk_class: RiskClass = RiskClass.WRITE,
) -> ToolDescriptor:
    tool_name = str(tool.get("name") or "").strip()
    if not tool_name:
        raise ValueError("MCP tool is missing a name.")
    schema = tool.get("inputSchema") or tool.get("input_schema") or {
        "type": "object",
        "properties": {},
    }
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return ToolDescriptor(
        name=f"mcp.{_tool_name(server.name)}.{_tool_name(tool_name)}",
        description=str(tool.get("description") or f"MCP tool {tool_name}"),
        input_schema=schema,
        risk_class=risk_class,
        idempotency=Idempotency.CONDITIONALLY_IDEMPOTENT,
        timeout_s=30.0,
        max_output_bytes=256_000,
        source="mcp",
        source_id=server.id,
    )


def descriptors_from_tools(
    server: MCPServer,
    tools: list[dict[str, Any]],
    *,
    risk_class: RiskClass = RiskClass.WRITE,
) -> list[ToolDescriptor]:
    return [
        descriptor_from_tool(server, tool, risk_class=risk_class)
        for tool in tools
        if isinstance(tool, dict) and tool.get("name")
    ]
