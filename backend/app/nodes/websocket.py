"""WebSocket node (spec 7).

Sends a message via WebSocket and optionally waits for a response.
Uses the `websockets` package (a core dependency) — httpx has no
WebSocket client.

Supports: custom headers (auth), multiple response messages,
configurable reconnection attempts.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import websockets
from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class WebSocketParams(BaseModel):
    url: str = Field(min_length=1, description="WebSocket server URL (ws:// or wss://).")
    message: str = Field(default="", description="Message to send.")
    message_type: Literal["text", "binary"] = Field(
        default="text", description="Type of message to send."
    )
    timeout_seconds: float = Field(
        default=10.0, description="Timeout for recv operation."
    )
    wait_for_response: bool = Field(
        default=False,
        description="Wait for a response message before returning.",
    )
    max_messages: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Max response messages to collect when wait_for_response=True.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Custom headers for the WebSocket handshake (e.g., Authorization).",
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Number of connection retry attempts on failure.",
    )


@register
class WebSocketNode(BaseNode[WebSocketParams]):
    node_type = "websocket"
    display_name = "WebSocket"
    version = 2
    description = "Send/receive messages via WebSocket with auth headers and retry support."
    category = "Network"
    icon = "📡"
    parameters_schema = WebSocketParams
    credential_types = []

    async def run(
        self,
        ctx: NodeContext,
        params: WebSocketParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        ws_url = params.url if params.url.startswith(("ws://", "wss://")) else f"ws://{params.url}"

        output_items: list[dict[str, Any]] = []
        last_error: Exception | None = None

        for attempt in range(params.max_retries + 1):
            try:
                async with websockets.connect(
                    ws_url,
                    open_timeout=params.timeout_seconds,
                    additional_headers=params.headers or None,
                ) as ws:
                    # Send message
                    if params.message_type == "text":
                        await ws.send(params.message)
                    else:
                        await ws.send(params.message.encode("utf-8"))

                    # Wait for response(s) if requested
                    if params.wait_for_response:
                        messages: list[dict[str, Any]] = []
                        for _ in range(params.max_messages):
                            try:
                                msg = await asyncio.wait_for(
                                    ws.recv(), timeout=params.timeout_seconds
                                )
                                if isinstance(msg, bytes):
                                    messages.append({"type": "binary", "data": msg.hex(), "size": len(msg)})
                                else:
                                    messages.append({"type": "text", "data": msg})
                            except asyncio.TimeoutError:
                                break
                        if len(messages) == 1:
                            output_items.append(messages[0])
                        elif messages:
                            output_items.append({"messages": messages, "count": len(messages)})
                        else:
                            output_items.append({"messages": [], "count": 0})
                    else:
                        output_items.append({"sent": True, "sent_bytes": len(params.message)})

                # Success — break out of retry loop
                break

            except asyncio.TimeoutError:
                last_error = NodeExecutionError(
                    f"WebSocket did not respond within {params.timeout_seconds}s.",
                    code="WEBSOCKET_TIMEOUT",
                    node_id=self.node_type,
                    retryable=True,
                )
                if attempt < params.max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise last_error from None

            except Exception as exc:
                last_error = NodeExecutionError(
                    f"WebSocket error: {exc}",
                    code="WEBSOCKET_ERROR",
                    node_id=self.node_type,
                    retryable=True,
                )
                if attempt < params.max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise last_error from exc

        return NodeResult(output_items=output_items)
