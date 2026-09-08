"""AI Agent node tests (Phase 12): autonomous tool-use loop."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from app.engine import expressions
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.ai_agent import AIAgentNode, AgentParams

FAKE_MODEL = {"model": "fake-model", "base_url": "http://localhost:9/v1", "api_key": ""}


async def _run_agent(
    params: dict,
    credentials: dict[str, Any] | None = None,
    monkeypatch=None,
):
    if monkeypatch is not None:
        async def fake_chat(credential, messages, **kwargs):
            CAPTURED.append((credential, messages, kwargs))
            return _sequence.pop(0)

        monkeypatch.setattr("app.nodes.ai_agent.chat_completion", fake_chat)

    node = AIAgentNode()
    context = expressions.build_context([{"task": "test"}], {}, "wf_1", "exec_1", credentials)
    p = AgentParams(**expressions.resolve(params, context))
    ctx = NodeContext(
        execution_id="exec_1",
        workflow_id="wf_1",
        logger=logging.getLogger("test"),
        http_client=httpx.AsyncClient(),
        credentials=credentials or {},
    )
    return await node.run(ctx, p, [{"task": "test"}])


_sequence: list[dict] = []
CAPTURED: list[tuple[dict, list[dict], dict]] = []


@pytest.fixture(autouse=True)
def _reset_state():
    _sequence.clear()
    CAPTURED.clear()


async def test_agent_missing_llm_credential_fails():
    with pytest.raises(NodeExecutionError) as ei:
        await _run_agent({"instructions": "You are a helpful agent", "input": "Hello"})
    assert ei.value.code == "CREDENTIALS_REQUIRED"


async def test_agent_single_tool_call(monkeypatch):
    """Agent calls a tool once, then returns final answer."""
    _sequence.extend([
        # First call: agent decides to call current_time
        {"content": None, "tool_calls": [{"id": "c1", "function": {"name": "current_time", "arguments": "{}"}}]},
        # Second call: agent gives final answer
        {"content": '{"action": "final", "answer": "The time is 12:00"}', "tool_calls": []},
    ])
    result = await _run_agent(
        {
            "instructions": "Use tools to answer the user's question.",
            "input": "What time is it?",
        },
        {"llm": FAKE_MODEL},
        monkeypatch,
    )
    item = result.items_for("main")[0]
    assert "The time is 12:00" in item["result"]


async def test_agent_multi_tool_sequence(monkeypatch):
    """Agent calls multiple tools in sequence before final answer."""
    _sequence.extend([
        # 1. Get current time
        {"content": None, "tool_calls": [{"id": "c1", "function": {"name": "current_time", "arguments": "{}"}}]},
        # 2. Query database
        {"content": None, "tool_calls": [{"id": "c2", "function": {"name": "database_query", "arguments": '{"sql": "SELECT 1"}'}}]},
        # 3. Final answer
        {"content": '{"action": "final", "answer": "Time checked and DB queried"}', "tool_calls": []},
    ])
    result = await _run_agent(
        {
            "instructions": "Use tools as needed.",
            "input": "Check time and run a simple query",
        },
        {"llm": FAKE_MODEL, "database": {"dsn": "sqlite:///:memory:"}},
        monkeypatch,
    )
    item = result.items_for("main")[0]
    assert "Time checked and DB queried" in item["result"]


async def test_agent_tool_error_continues_loop(monkeypatch):
    """When a tool errors, agent gets the error and can retry or adapt."""
    _sequence.clear()
    _sequence.extend([
        # First tool call fails
        {"content": None, "tool_calls": [{"id": "c1", "function": {"name": "current_time", "arguments": "{}"}}]},
        # Agent retries
        {"content": None, "tool_calls": [{"id": "c2", "function": {"name": "current_time", "arguments": "{}"}}]},
        # Success
        {"content": '{"action": "final", "answer": "Recovered!"}', "tool_calls": []},
    ])

    call_state = {"called": False}

    async def failing_then_ok(ctx, name, args):
        if not call_state["called"]:
            call_state["called"] = True
            raise RuntimeError("transient failure")
        return "2026-01-01T12:00:00Z"

    import app.nodes.ai_agent as agent_module
    monkeypatch.setattr(agent_module, "run_tool", failing_then_ok)

    result = await _run_agent(
        {"instructions": "Keep trying", "input": "Get time"},
        {"llm": FAKE_MODEL},
        monkeypatch,
    )
    item = result.items_for("main")[0]
    assert "Recovered" in item["result"]


async def test_agent_max_iterations_stops(monkeypatch):
    """Agent stops after max_iterations without final answer."""
    # Return tool calls forever, never a final answer
    _sequence.extend([
        {"content": None, "tool_calls": [{"id": f"c{i}", "function": {"name": "current_time", "arguments": "{}"}}]}
        for i in range(15)
    ])

    with pytest.raises(NodeExecutionError) as ei:
        await _run_agent(
            {"instructions": "loop", "input": "loop", "max_iterations": 3},
            {"llm": FAKE_MODEL},
            monkeypatch,
        )
    assert ei.value.code == "AI_MAX_ITERATIONS"


async def test_agent_final_answer_without_tool_calls(monkeypatch):
    """Agent can answer directly without using tools."""
    _sequence.append({"content": '{"action": "final", "answer": "Direct answer"}', "tool_calls": []})

    result = await _run_agent(
        {"instructions": "Answer directly", "input": "What is 2+2?"},
        {"llm": FAKE_MODEL},
        monkeypatch,
    )
    item = result.items_for("main")[0]
    assert item["result"] == "Direct answer"