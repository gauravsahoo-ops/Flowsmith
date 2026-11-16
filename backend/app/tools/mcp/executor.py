"""MCP tool execution adapter.

Composes the MCP policy decision with the existing HTTP/SSE MCP client. The
caller supplies a resolved auth token (or a prebuilt client); this module never
reads credentials from the database.
"""

from __future__ import annotations

import json
from typing import Any

from app.models import MCPServer
from app.metrics import mcp_tool_calls
from app.platform.contracts import (
    PolicyOutcome,
    RiskClass,
    ToolResult,
    ToolResultStatus,
)
from app.tools.mcp.client_factory import build_mcp_client
from app.tools.mcp.policy import evaluate_tool_policy

MAX_OUTPUT_BYTES = 256_000


def _bounded(value: Any) -> Any:
    if value is None:
        return None
    try:
        rendered = value if isinstance(value, str) else json.dumps(value, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    if len(rendered.encode("utf-8", errors="replace")) <= MAX_OUTPUT_BYTES:
        return value
    return rendered[:MAX_OUTPUT_BYTES] + "... (truncated)"


async def invoke_tool(
    server: MCPServer,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    risk_class: RiskClass = RiskClass.WRITE,
    approval_granted: bool = False,
    auth_token: str | None = None,
    headers: dict[str, str] | None = None,
    client: Any = None,
    timeout_s: float = 30.0,
) -> ToolResult:
    result = await _invoke_tool(
        server,
        tool_name,
        arguments,
        risk_class=risk_class,
        approval_granted=approval_granted,
        auth_token=auth_token,
        headers=headers,
        client=client,
        timeout_s=timeout_s,
    )
    mcp_tool_calls.inc((result.status.value,))
    return result


async def _invoke_tool(
    server: MCPServer,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    risk_class: RiskClass = RiskClass.WRITE,
    approval_granted: bool = False,
    auth_token: str | None = None,
    headers: dict[str, str] | None = None,
    client: Any = None,
    timeout_s: float = 30.0,
) -> ToolResult:
    """Authorize and invoke one MCP tool.

    Returns a normalized ``ToolResult``; never raises for policy or provider
    failures, so the agent can feed the observation back to the model.
    """
    decision = evaluate_tool_policy(
        server,
        tool_name,
        risk_class=risk_class,
        approval_granted=approval_granted,
    )
    if decision.outcome is PolicyOutcome.DENY:
        return ToolResult(
            tool_name=tool_name,
            status=ToolResultStatus.DENIED,
            error_code=decision.reason_code,
        )
    if decision.outcome is PolicyOutcome.APPROVAL_REQUIRED:
        return ToolResult(
            tool_name=tool_name,
            status=ToolResultStatus.APPROVAL_REQUIRED,
            error_code="APPROVAL_REQUIRED",
        )

    if server.auth_type in ("bearer", "credential") and not auth_token and client is None:
        return ToolResult(
            tool_name=tool_name,
            status=ToolResultStatus.ERROR,
            error_code="MCP_CREDENTIAL_REQUIRED",
        )

    if client is None:
        try:
            client = build_mcp_client(
                server, auth_token=auth_token, headers=headers
            )
        except Exception as exc:  # noqa: BLE001 - normalize configuration failures
            return ToolResult(
                tool_name=tool_name,
                status=ToolResultStatus.ERROR,
                error_code=getattr(exc, "code", type(exc).__name__),
            )
        owned_client = True
    else:
        owned_client = False

    try:
        result = await client.call_tool(
            tool_name,
            dict(arguments),
            timeout_s=max(0.1, float(timeout_s)),
        )
    except Exception as exc:  # noqa: BLE001 - normalize provider failures
        return ToolResult(
            tool_name=tool_name,
            status=ToolResultStatus.ERROR,
            error_code=type(exc).__name__,
        )
    finally:
        if owned_client:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 - cleanup is best effort
                    pass

    return ToolResult(
        tool_name=tool_name,
        status=ToolResultStatus.SUCCESS,
        output=_bounded(result),
    )
