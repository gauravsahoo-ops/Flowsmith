"""AI node tests (Phase 8): prompts, json mode, tool-calling loop,
turn limits, and missing-credential errors. The chat client is stubbed
so tests never touch the network."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from app.engine import expressions
from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.ai import AINode, AIParams

FAKE_MODEL = {"model": "fake-model", "base_url": "http://localhost:9/v1", "api_key": ""}


async def _run(params: dict, credentials: dict[str, Any] | None = None, monkeypatch=None):
    if monkeypatch is not None:
        async def fake_chat(cred, msgs, **kwargs):
            CAPTURED.append((cred, msgs, kwargs))
            return _sequence.pop(0)

        monkeypatch.setattr("app.nodes.ai.chat_completion", fake_chat)
    node = AINode()
    context = expressions.build_context([{"hello": "world"}], {}, "wf_1", "exec_1", credentials)
    p = AIParams(**expressions.resolve(params, context))
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
        credentials=credentials or {},
    )
    return await node.run(ctx, p, [{"hello": "world"}])


_sequence: list[dict] = []
CAPTURED: list[tuple[dict, list[dict], dict]] = []


@pytest.fixture(autouse=True)
def _reset_state():
    _sequence.clear()
    CAPTURED.clear()


async def test_missing_llm_credential_fails():
    with pytest.raises(NodeExecutionError) as ei:
        await _run({"prompt": "hi"})
    assert ei.value.code == "CREDENTIALS_REQUIRED"


async def test_basic_prompt(monkeypatch):
    _sequence.append({"content": "Hello world", "tool_calls": []})
    result = await _run({"prompt": "Say hi"}, {"llm": FAKE_MODEL}, monkeypatch)
    item = result.items_for("main")[0]
    assert item["response"] == "Hello world"
    assert item["turns"] == 1
    assert item["model"] == "fake-model"


async def test_system_message_and_expression_params(monkeypatch):
    _sequence.append({"content": "ok", "tool_calls": []})
    await _run(
        {"prompt": "You are {{ $json.hello }}", "system_message": "Be brief"},
        {"llm": FAKE_MODEL}, monkeypatch,
    )
    assert CAPTURED[-1][1][0]["content"] == "Be brief"
    assert "world" in CAPTURED[-1][1][1]["content"]


async def test_json_response_format_parses(monkeypatch):
    _sequence.append({"content": '{"ok": true, "n": 2}', "tool_calls": []})
    result = await _run({"prompt": "x", "response_format": "json"}, {"llm": FAKE_MODEL}, monkeypatch)
    assert result.items_for("main")[0]["response"] == {"ok": True, "n": 2}


async def test_json_response_format_falls_back_to_text(monkeypatch):
    _sequence.append({"content": "not json at all", "tool_calls": []})
    result = await _run({"prompt": "x", "response_format": "json"}, {"llm": FAKE_MODEL}, monkeypatch)
    assert result.items_for("main")[0]["response"] == "not json at all"


async def test_tool_calling_loop(monkeypatch):
    _sequence.append({"content": None, "tool_calls": [{"id": "c1", "function": {"name": "current_time", "arguments": "{}"}}]})
    _sequence.append({"content": "It is 2026", "tool_calls": []})
    result = await _run({"prompt": "What time is it?", "tools": ["current_time"]}, {"llm": FAKE_MODEL}, monkeypatch)
    item = result.items_for("main")[0]
    assert item["response"] == "It is 2026"
    assert item["turns"] == 2
    assert item["tool_calls"] == [{"tool": "current_time", "arguments": {}}]


async def test_tool_error_surfaces_to_model(monkeypatch):
    def bad_tool(ctx, name, args):
        raise RuntimeError("boom")

    import app.nodes.ai as ai_module

    monkeypatch.setattr(ai_module, "run_tool", bad_tool)
    _sequence.append({"content": None, "tool_calls": [{"id": "c1", "function": {"name": "current_time", "arguments": "{}"}}]})
    _sequence.append({"content": "done", "tool_calls": []})
    await _run({"prompt": "x", "tools": ["current_time"]}, {"llm": FAKE_MODEL}, monkeypatch)
    tool_msg = [m for m in CAPTURED[-1][1] if m.get("role") == "tool"]
    assert tool_msg and "boom" in json.loads(tool_msg[0]["content"])["error"]


async def test_max_turns_hit(monkeypatch):
    _sequence.extend([
        {"content": None, "tool_calls": [{"id": f"c{i}", "function": {"name": "current_time", "arguments": "{}"}}]}
        for i in range(10)
    ])
    with pytest.raises(NodeExecutionError) as ei:
        await _run({"prompt": "x", "tools": ["current_time"], "max_turns": 3}, {"llm": FAKE_MODEL}, monkeypatch)
    assert ei.value.code == "AI_MAX_TURNS"


async def test_unknown_tool_rejected(monkeypatch):
    _sequence.append({"content": "x", "tool_calls": []})
    with pytest.raises(NodeExecutionError) as ei:
        await _run({"prompt": "x", "tools": ["nope"]}, {"llm": FAKE_MODEL}, monkeypatch)
    assert ei.value.code == "INVALID_TOOLS"


async def test_network_error_is_llm_error():
    from app.ai import client as client_mod
    from app.ai.client import LLMError

    async def boom(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    try:
        with pytest.raises(LLMError) as ei:
            await client_mod.chat_completion(
                FAKE_MODEL,
                [{"role": "user", "content": "hi"}],
                http_client=client,
            )
        assert ei.value.code == "LLM_NETWORK_ERROR"
    finally:
        await client.aclose()
