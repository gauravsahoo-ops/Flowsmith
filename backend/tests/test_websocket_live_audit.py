"""Live integration tests for the WebSocket node against a real echo server."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time

import httpx
import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.websocket import WebSocketNode, WebSocketParams


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def echo_server():
    """Start a local WebSocket echo server in a background process."""
    proc = subprocess.Popen(
        [sys.executable, "ws_echo_server.py"],
        cwd="D:\\my-automation-tool\\backend",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)  # let the server bind
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def make_ctx() -> NodeContext:
    return NodeContext(
        execution_id="test",
        workflow_id="test",
        node_id="ws",
        logger=logging.getLogger("test"),
        http_client=httpx.AsyncClient(),
        emit_event=lambda *a, **k: None,
        user_id=1,
    )


async def run_ws(params: WebSocketParams) -> dict:
    node = WebSocketNode()
    ctx = make_ctx()
    result = await node.run(ctx, params, [])
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_echo_server_connect_and_send():
    """1. Connect → send 'hello' → receive echo response."""
    result = await run_ws(WebSocketParams(
        url="ws://localhost:8765",
        message="hello",
        wait_for_response=True,
    ))
    assert result.output_items is not None
    assert len(result.output_items) == 1
    item = result.output_items[0]
    resp = json.loads(item["data"])
    assert resp["echo"] == "hello"
    assert resp["server"] == "test"


@pytest.mark.asyncio
async def test_fire_and_forget():
    """2. Send message without waiting → verify sent=True."""
    result = await run_ws(WebSocketParams(
        url="ws://localhost:8765",
        message="fire-and-forget",
        wait_for_response=False,
    ))
    assert result.output_items is not None
    item = result.output_items[0]
    assert item["sent"] is True
    assert item["sent_bytes"] == len("fire-and-forget")


@pytest.mark.asyncio
async def test_wait_for_response():
    """3. Send message → wait for response → verify content."""
    result = await run_ws(WebSocketParams(
        url="ws://localhost:8765",
        message="ping",
        wait_for_response=True,
    ))
    assert result.output_items is not None
    resp = json.loads(result.output_items[0]["data"])
    assert resp["echo"] == "ping"


@pytest.mark.asyncio
async def test_invalid_url():
    """4. Connect to ws://localhost:99999 → verify error handling."""
    node = WebSocketNode()
    ctx = make_ctx()
    params = WebSocketParams(
        url="ws://localhost:99999",
        message="fail",
        timeout_seconds=3.0,
    )
    with pytest.raises(NodeExecutionError) as exc_info:
        await node.run(ctx, params, [])
    assert exc_info.value.code in ("WEBSOCKET_ERROR", "WEBSOCKET_TIMEOUT")


@pytest.mark.asyncio
async def test_timeout():
    """5. Connect to a server that never responds → verify timeout."""
    # Use the echo server but send binary and don't wait – we need a server
    # that accepts connection but never sends back.  We'll use the real echo
    # server with wait_for_response=True but send a message that the echo
    # server will reply to. To simulate timeout we connect to a port that
    # accepts TCP but never replies.  Easiest: connect to a listening socket
    # we create that does nothing.
    import socket
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("localhost", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    try:
        node = WebSocketNode()
        ctx = make_ctx()
        params = WebSocketParams(
            url=f"ws://localhost:{port}",
            message="timeout-test",
            wait_for_response=True,
            timeout_seconds=2.0,
        )
        with pytest.raises(NodeExecutionError) as exc_info:
            await node.run(ctx, params, [])
        assert exc_info.value.code == "WEBSOCKET_TIMEOUT"
    finally:
        listener.close()


@pytest.mark.asyncio
async def test_json_message():
    """6. Send JSON string → verify echo server returns it."""
    payload = json.dumps({"key": "value", "num": 42})
    result = await run_ws(WebSocketParams(
        url="ws://localhost:8765",
        message=payload,
        wait_for_response=True,
    ))
    assert result.output_items is not None
    resp = json.loads(result.output_items[0]["data"])
    assert resp["echo"] == payload
    assert resp["type"] == "text"


@pytest.mark.asyncio
async def test_binary_message():
    """7. Send binary data → verify handling."""
    result = await run_ws(WebSocketParams(
        url="ws://localhost:8765",
        message="deadbeef",
        message_type="binary",
        wait_for_response=True,
    ))
    assert result.output_items is not None
    resp = json.loads(result.output_items[0]["data"])
    # The echo server returns hex of the received bytes
    assert resp["type"] == "binary"
    # "deadbeef" as UTF-8 bytes → hex is 6465616462656566
    assert resp["echo"] == "6465616462656566"
