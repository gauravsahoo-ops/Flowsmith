"""Mid-ReAct-loop tool approval.

Proves the agent pauses *before* a gated tool executes, persists an encrypted
checkpoint, and resumes the exact pending call after a durable decision.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.agents.tool_execution import (
    ToolApprovalRequired,
    execute_tool,
    preflight_tool_call,
)
from app.engine.errors import NodeExecutionError
from app.engine.executor import execute_workflow
from app.engine.node_base import NodeContext
from app.nodes.ai_agent import AIAgentNode, AgentParams
from app.platform.contracts import ToolResult, ToolResultStatus
from app.security.crypto import decrypt_text, encrypt_text
from app.tools.gateway import ToolGateway
from tests.conftest import conn, make_node, make_workflow


class _FakeExecution:
    id = "exec_tool_pause"
    status = "running"
    pause_state = None
    node_statuses = {}
    workflow_id = "wf_tool_pause"
    organization_id = "org"
    workspace_id = "ws"
    user_id = 7
    finished_at = None
    error = None


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def scalars(self):
        return self

    def first(self):
        return None


class _FakeSession:
    def __init__(self, row):
        self.row = row

    def execute(self, *_args, **_kwargs):
        return _FakeResult(self.row)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _ctx(execution_id="exec_tool_pause", node_id="agent") -> NodeContext:
    return NodeContext(
        execution_id=execution_id,
        workflow_id="wf_tool_pause",
        node_id=node_id,
        logger=logging.getLogger("test.agent_tool_approval"),
        http_client=httpx.AsyncClient(),
        credentials={
            "llm": {"provider": "fake", "model": "fake-model", "api_key": ""}
        },
    )


def _tool_call(name="datatable_insert_row", args=None, call_id="call_1"):
    return {
        "id": call_id,
        "function": {
            "name": name,
            "arguments": json.dumps(args or {"row": {"name": "Ada"}}),
        },
    }


def _encrypted_state(*, execution_id="exec_tool_pause", node_id="agent", approved=True):
    call = _tool_call()
    state = {
        "execution_id": execution_id,
        "workflow_id": "wf_tool_pause",
        "node_id": node_id,
        "iteration": 0,
        "messages": [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "Insert the row"},
            {"role": "assistant", "content": None, "tool_calls": [call]},
        ],
        "execution_trace": [],
        "tools_used": [],
        "step_trace": {
            "iteration": 1,
            "thought": "",
            "tool_calls": [],
            "duration_ms": 1.0,
        },
        "tool_calls": [call],
        "pending_index": 0,
        "user_input": "Insert the row",
    }
    return encrypt_text(json.dumps(state)).decode("ascii"), state, call


def test_preflight_pauses_only_for_gated_tools():
    gateway = ToolGateway.from_native_tools()

    with pytest.raises(ToolApprovalRequired) as exc_info:
        preflight_tool_call(
            None,
            "datatable_insert_row",
            {"row": {"name": "Ada"}},
            declared_tools=["datatable_insert_row"],
            gateway=gateway,
            policy_enabled=True,
        )
    assert exc_info.value.tool_name == "datatable_insert_row"
    assert exc_info.value.risk_class == "write"
    assert exc_info.value.risk_tier == 1
    assert exc_info.value.quorum == 1

    preflight_tool_call(
        None,
        "current_time",
        {},
        declared_tools=["current_time"],
        gateway=gateway,
        policy_enabled=True,
    )

    with pytest.raises(ToolApprovalRequired) as destructive:
        preflight_tool_call(
            None,
            "workflow_delete_node",
            {"node_id": "n1"},
            declared_tools=["workflow_delete_node"],
            gateway=gateway,
            policy_enabled=True,
        )
    assert destructive.value.risk_class == "destructive"
    assert destructive.value.risk_tier == 3
    assert destructive.value.quorum == 2


def test_execute_tool_can_raise_instead_of_returning_pending():
    class Gateway:
        async def invoke(self, invocation, *, capabilities, approval_granted=False):
            return ToolResult(
                tool_name=invocation.tool_name,
                status=ToolResultStatus.APPROVAL_REQUIRED,
                error_code="APPROVAL_REQUIRED",
            )

    with pytest.raises(ToolApprovalRequired):
        import asyncio

        asyncio.run(
            execute_tool(
                None,
                "datatable_insert_row",
                {"x": 1},
                declared_tools=["datatable_insert_row"],
                gateway=Gateway(),
                policy_enabled=True,
                raise_on_approval=True,
            )
        )


@pytest.mark.asyncio
async def test_agent_pauses_before_gated_tool_and_encrypts_state(monkeypatch):
    import app.nodes.ai_agent as agent_module

    async def fake_chat(_cred, messages, **_kwargs):
        return {"content": None, "tool_calls": [_tool_call()]}

    def fake_preflight(_ctx, name, args, **_kwargs):
        raise ToolApprovalRequired(name, args, risk_class="write", risk_tier=1)

    async def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("gated tool must not execute before approval")

    monkeypatch.setattr(agent_module, "chat_completion", fake_chat)
    monkeypatch.setattr(agent_module, "preflight_tool_call", fake_preflight)
    monkeypatch.setattr(agent_module, "execute_tool", forbidden_execute)

    execution = _FakeExecution()
    fake_db = _FakeSession(execution)
    monkeypatch.setattr("app.db.get_session", lambda: fake_db)
    monkeypatch.setattr(
        "app.approvals.service.create_request",
        lambda *_args, **_kwargs: SimpleNamespace(id="approval_1"),
    )

    node = AIAgentNode()
    params = AgentParams(
        instructions="Insert rows when asked.",
        input="Insert the row",
        tools=["datatable_insert_row"],
        memory_type="none",
    )
    result = await node.run(_ctx(), params, [{"task": "Insert the row"}])

    assert result.metadata["waiting_approval"] is True
    assert result.metadata["type"] == "tool_approval"
    assert result.metadata["tool_name"] == "datatable_insert_row"
    assert result.metadata["approval_id"] == "approval_1"
    assert execution.status == "waiting_approval"
    assert execution.node_statuses["agent"] == "waiting_approval"
    pause = execution.pause_state
    assert pause["type"] == "tool_approval"
    assert pause["tool_name"] == "datatable_insert_row"
    assert pause["quorum"] == 1
    assert "state" in pause

    restored = json.loads(decrypt_text(pause["state"]))
    assert restored["execution_id"] == "exec_tool_pause"
    assert restored["node_id"] == "agent"
    assert restored["pending_index"] == 0
    assert restored["tool_calls"][0]["function"]["name"] == "datatable_insert_row"


@pytest.mark.asyncio
async def test_agent_resumes_approved_tool_and_continues_loop(monkeypatch):
    import app.nodes.ai_agent as agent_module

    blob, _state, _call = _encrypted_state()
    captured_messages = []
    tool_calls = []

    async def fake_chat(_cred, messages, **_kwargs):
        captured_messages.append(list(messages))
        return {"content": "Inserted the row.", "tool_calls": []}

    async def fake_execute(_ctx, name, args, **kwargs):
        tool_calls.append((name, args, kwargs))
        return "1 row inserted"

    async def no_preflight(*_args, **_kwargs):
        return None

    monkeypatch.setattr(agent_module, "chat_completion", fake_chat)
    monkeypatch.setattr(agent_module, "execute_tool", fake_execute)
    monkeypatch.setattr(agent_module, "preflight_tool_call", no_preflight)

    ctx = _ctx()
    await ctx.storage.set(
        "_approval_data",
        {
            "pause_type": "tool_approval",
            "approved": True,
            "approved_by": 7,
            "state": blob,
        },
    )
    result = await AIAgentNode().run(
        ctx,
        AgentParams(
            instructions="Insert rows when asked.",
            input="Insert the row",
            tools=["datatable_insert_row"],
            memory_type="none",
        ),
        [{"task": "Insert the row"}],
    )

    assert result.items_for("main")[0]["final_answer"] == "Inserted the row."
    assert len(tool_calls) == 1
    name, _args, kwargs = tool_calls[0]
    assert name == "datatable_insert_row"
    assert kwargs["approval_granted"] is True
    assert kwargs["policy_enabled"] is True
    assert any(
        message.get("role") == "tool"
        and message.get("content") == "1 row inserted"
        for message in captured_messages[0]
    )


@pytest.mark.asyncio
async def test_agent_rejects_tool_without_executing(monkeypatch):
    import app.nodes.ai_agent as agent_module

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("rejected tool must not execute")

    monkeypatch.setattr(agent_module, "execute_tool", forbidden)

    ctx = _ctx()
    await ctx.storage.set(
        "_approval_data",
        {"pause_type": "tool_approval", "approved": False},
    )
    with pytest.raises(NodeExecutionError) as exc_info:
        await AIAgentNode().run(
            ctx,
            AgentParams(
                instructions="Insert rows when asked.",
                input="Insert the row",
                tools=["datatable_insert_row"],
                memory_type="none",
            ),
            [{"task": "Insert the row"}],
        )
    assert exc_info.value.code == "APPROVAL_REJECTED"


@pytest.mark.asyncio
async def test_engine_stops_scheduling_after_a_pause(monkeypatch):
    execution = _FakeExecution()
    monkeypatch.setattr("app.db.get_session", lambda: _FakeSession(execution))
    monkeypatch.setattr(
        "app.approvals.service.create_request",
        lambda *_args, **_kwargs: SimpleNamespace(id="approval_engine"),
    )

    wf = make_workflow(
        [
            make_node("trigger", "manual_trigger"),
            make_node(
                "gate",
                "human_approval",
                parameters={"message": "Approve this step?"},
            ),
            make_node(
                "after",
                "set_data",
                parameters={"fields": {"result": "should not run"}},
            ),
        ],
        [conn("trigger", "gate"), conn("gate", "after")],
    )
    result = await execute_workflow(wf, [{"value": "ok"}], execution_id="exec_tool_pause")

    assert result.paused is True
    assert result.paused_node_id == "gate"
    assert "after" not in result.results
    assert all(step["node_id"] != "after" for step in result.trace)
    gate_step = next(step for step in result.trace if step["node_id"] == "gate")
    assert gate_step["status"] == "waiting_approval"


def test_tool_approval_pause_and_resume_end_to_end(client, monkeypatch):
    """API -> queue -> engine: pause mid-loop, decide, resume, finish."""
    import time

    import app.nodes.ai_agent as agent_module
    from tests.test_api.conftest import auth_headers, register

    headers = auth_headers(register(client, email="tool_approval_e2e@example.com")["token"])
    llm = client.post(
        "/api/credentials",
        json={
            "name": "e2e-agent-llm",
            "type": "llm",
            "data": {"base_url": "http://localhost:9/v1", "model": "fake", "api_key": "k"},
        },
        headers=headers,
    )
    assert llm.status_code == 201, llm.text
    llm_id = llm.json()["data"]["id"]
    calls = {"chat": 0, "tools": []}

    async def fake_chat(_cred, messages, **_kwargs):
        calls["chat"] += 1
        if calls["chat"] == 1:
            return {"content": None, "tool_calls": [_tool_call()]}
        return {"content": "Inserted the row.", "tool_calls": []}

    async def fake_execute(_ctx, name, args, **kwargs):
        calls["tools"].append((name, args, kwargs))
        return "1 row inserted"

    def fake_preflight(_ctx, name, args, **_kwargs):
        raise ToolApprovalRequired(name, args, risk_class="write", risk_tier=1)

    monkeypatch.setattr(agent_module, "chat_completion", fake_chat)
    monkeypatch.setattr(agent_module, "execute_tool", fake_execute)
    monkeypatch.setattr(agent_module, "preflight_tool_call", fake_preflight)

    wf_id = "wf_tool_approval_e2e"
    wf = {
        "id": wf_id,
        "name": "Tool approval e2e",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "parameters": {}},
            {
                "id": "agent",
                "type": "ai_agent",
                "parameters": {
                    "instructions": "Insert rows when asked.",
                    "input": "Insert the row",
                    "tools": ["datatable_insert_row"],
                    "memory_type": "none",
                },
                "credentials": {"llm": llm_id},
            },
            {
                "id": "after",
                "type": "set_data",
                "parameters": {
                    "fields": {"result": "{{ $node.agent.json.final_answer }}"}
                },
            },
        ],
        "connections": [
            {"source": "trigger", "target": "agent"},
            {"source": "agent", "target": "after"},
        ],
        "settings": {},
    }
    created = client.post("/api/workflows", json=wf, headers=headers)
    assert created.status_code == 201, created.text

    run = client.post(
        f"/api/workflows/{wf_id}/run", json={"data": {"value": "ok"}}, headers=headers
    ).json()["data"]
    execution_id = run["execution_id"]

    deadline = time.monotonic() + 20
    data = {}
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("queued", "running", "cancelling"):
            break
        time.sleep(0.05)

    assert data["status"] == "waiting_approval", data.get("error")
    pause = data["pause_state"]
    assert pause["type"] == "tool_approval"
    assert pause["tool_name"] == "datatable_insert_row"
    assert pause["message"]
    assert "state" not in pause
    assert calls["tools"] == []

    deadline = time.monotonic() + 10
    pending = []
    while time.monotonic() < deadline:
        body = client.get("/api/approvals", headers=headers).json()
        pending = [row for row in body.get("data", []) if row["run_id"] == execution_id]
        if pending:
            break
        time.sleep(0.05)
    assert pending, "pause did not create a durable approval request"
    approval_id = pending[0]["id"]

    decided = client.post(
        f"/api/approvals/{approval_id}/decide",
        json={"approved": True, "nonce": "tool-approval-e2e-nonce"},
        headers=headers,
    )
    assert decided.status_code == 200, decided.text

    resumed = client.post(
        f"/api/executions/{execution_id}/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        data = client.get(f"/api/executions/{execution_id}", headers=headers).json()["data"]
        if data["status"] not in ("queued", "running", "cancelling"):
            break
        time.sleep(0.05)

    assert data["status"] == "success", data.get("error")
    agent_items = data["results"]["outputs"]["agent"]["main"]
    assert agent_items[0]["final_answer"] == "Inserted the row."
    assert agent_items[0]["tools_used"] == ["datatable_insert_row"]
    after_items = data["results"]["outputs"]["after"]["main"]
    assert after_items and after_items[0]["result"] == "Inserted the row."
    assert calls["chat"] == 2
    assert len(calls["tools"]) == 1
    _name, _args, kwargs = calls["tools"][0]
    assert kwargs["approval_granted"] is True
    assert kwargs["policy_enabled"] is True

def test_resume_requires_quorum_for_high_risk_tool(client):
    """A tier-3 tool cannot resume until every required approver signs off."""
    from app.approvals import service as approvals
    from app.db import get_session
    from app.models import ApprovalRequest, Execution, User, WorkflowRecord
    from tests.test_api.conftest import auth_headers, register

    registered = register(client, email="tool_quorum@example.com")
    headers = auth_headers(registered["token"])
    user_id = registered["user"]["id"]
    wf_id = "wf_tool_quorum"
    wf = {
        "id": wf_id,
        "name": "Tool quorum",
        "nodes": [{"id": "trigger", "type": "manual_trigger", "parameters": {}}],
        "connections": [],
        "settings": {},
    }
    assert client.post("/api/workflows", json=wf, headers=headers).status_code == 201

    with get_session() as db:
        user = db.get(User, user_id)
        assert user is not None
        record = db.get(WorkflowRecord, wf_id)
        assert record is not None
        execution = Execution(
            id="exec_tool_quorum",
            workflow_id=wf_id,
            user_id=user_id,
            workflow_version=1,
            workflow_data=record.data,
            trigger="manual",
            trigger_data=[{}],
            status="waiting_approval",
            pause_state={
                "type": "tool_approval",
                "node_id": "agent",
                "tool_name": "workflow_delete_node",
                "approvers": [],
                "timeout_hours": 24,
                "arguments": {},
                "state": "k0:not-used-before-quorum",
            },
        )
        db.add(execution)
        db.commit()

        request = approvals.create_request(
            db,
            run_id=execution.id,
            node_id="agent",
            workflow_id=wf_id,
            requested_by=user_id,
            reason="Delete a node",
            tool_name="workflow_delete_node",
            risk_tier=3,
            arguments={"node_id": "n1"},
            quorum=2,
            separation_of_duties=False,
            approvers=[],
            ttl_seconds=3600,
        )
        request_id = request.id
        execution.pause_state = {
            **(execution.pause_state or {}),
            "approval_id": request_id,
            "quorum": 2,
        }
        db.commit()

    resumed = client.post(
        "/api/executions/exec_tool_quorum/resume",
        json={"approved": True},
        headers=headers,
    )
    assert resumed.status_code == 409, resumed.text
    assert resumed.json()["detail"]["code"] == "APPROVAL_QUORUM_NOT_MET"

    with get_session() as db:
        execution = db.get(Execution, "exec_tool_quorum")
        request = db.get(ApprovalRequest, request_id)
        assert execution is not None and execution.status == "waiting_approval"
        assert request is not None and request.status == "pending"
        assert len((request.decision or {}).get("decisions") or []) == 1

@pytest.mark.asyncio
async def test_agent_rejects_resume_state_for_another_execution():
    blob, _state, _call = _encrypted_state(execution_id="exec_someone_else")
    ctx = _ctx()
    await ctx.storage.set(
        "_approval_data",
        {"pause_type": "tool_approval", "approved": True, "state": blob},
    )
    with pytest.raises(NodeExecutionError) as exc_info:
        await AIAgentNode().run(
            ctx,
            AgentParams(
                instructions="Insert rows when asked.",
                input="Insert the row",
                tools=["datatable_insert_row"],
                memory_type="none",
            ),
            [{"task": "Insert the row"}],
        )
    assert exc_info.value.code == "TOOL_APPROVAL_STATE_MISMATCH"

@pytest.mark.asyncio
async def test_agent_pauses_again_for_a_second_gated_call(monkeypatch):
    """A resumed batch pauses before the next gated call, preserving progress."""
    import app.nodes.ai_agent as agent_module

    first = _tool_call("datatable_insert_row", {"row": {"name": "Ada"}}, "c1")
    second = _tool_call("workflow_delete_node", {"node_id": "n1"}, "c2")
    state = {
        "execution_id": "exec_tool_pause",
        "workflow_id": "wf_tool_pause",
        "node_id": "agent",
        "iteration": 0,
        "messages": [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "Do both"},
            {"role": "assistant", "content": None, "tool_calls": [first, second]},
        ],
        "execution_trace": [],
        "tools_used": [],
        "step_trace": {
            "iteration": 1,
            "thought": "",
            "tool_calls": [],
            "duration_ms": 1.0,
        },
        "tool_calls": [first, second],
        "pending_index": 0,
        "user_input": "Do both",
    }
    blob = encrypt_text(json.dumps(state)).decode("ascii")
    executed = []

    async def fake_execute(_ctx, name, args, **kwargs):
        executed.append((name, args, kwargs))
        return "inserted"

    def fake_preflight(_ctx, name, args, **_kwargs):
        if name == "workflow_delete_node":
            raise ToolApprovalRequired(name, args, risk_class="destructive", risk_tier=3)

    async def forbidden_chat(*_args, **_kwargs):
        raise AssertionError("no LLM turn should run before the second approval")

    monkeypatch.setattr(agent_module, "execute_tool", fake_execute)
    monkeypatch.setattr(agent_module, "preflight_tool_call", fake_preflight)
    monkeypatch.setattr(agent_module, "chat_completion", forbidden_chat)

    execution = _FakeExecution()
    execution.status = "running"
    execution.pause_state = None
    fake_db = _FakeSession(execution)
    monkeypatch.setattr("app.db.get_session", lambda: fake_db)
    monkeypatch.setattr(
        "app.approvals.service.create_request",
        lambda *_args, **_kwargs: SimpleNamespace(id="approval_2"),
    )

    ctx = _ctx()
    await ctx.storage.set(
        "_approval_data",
        {"pause_type": "tool_approval", "approved": True, "state": blob},
    )
    result = await AIAgentNode().run(
        ctx,
        AgentParams(
            instructions="Do both.",
            input="Do both",
            tools=["datatable_insert_row", "workflow_delete_node"],
            memory_type="none",
        ),
        [{"task": "Do both"}],
    )

    assert result.metadata["waiting_approval"] is True
    assert result.metadata["tool_name"] == "workflow_delete_node"
    assert result.metadata["approval_id"] == "approval_2"
    assert len(executed) == 1
    assert executed[0][0] == "datatable_insert_row"
    assert executed[0][2]["approval_granted"] is True

    restored = json.loads(decrypt_text(execution.pause_state["state"]))
    assert restored["pending_index"] == 1
    assert len(restored["tool_calls"]) == 2
    assert restored["step_trace"]["tool_calls"][0]["name"] == "datatable_insert_row"
    assert any(
        message.get("role") == "tool" and message.get("content") == "inserted"
        for message in restored["messages"]
    )
