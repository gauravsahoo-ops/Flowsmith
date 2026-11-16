"""Phase 3 foundation tests: contracts, state machine, tool policy gateway."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.orchestration.state_machine import (
    InvalidTransition,
    transition,
)
from app.platform.contracts import (
    Checkpoint,
    EventEnvelope,
    Idempotency,
    RiskClass,
    RunSnapshot,
    RunStatus,
    ToolInvocation,
    ToolResultStatus,
)
from app.platform.events import (
    RUN_COMPLETED,
    InMemoryEventBus,
    idempotency_key,
    new_event,
)
from app.orchestration.coordinator import (
    InMemoryJobQueue,
    InMemoryRunStore,
    RunCoordinator,
    StartRun,
)
from app.tools.gateway import ToolGateway
from app.tools.registry import ToolRegistry


def test_run_state_machine_pause_resume_and_cancel():
    snap = RunSnapshot(run_id="run_1", status=RunStatus.QUEUED)
    snap = transition(snap, RunStatus.RUNNING, expected_version=0)
    assert snap.status is RunStatus.RUNNING
    assert snap.version == 1

    paused = transition(snap, RunStatus.WAITING_APPROVAL, expected_version=1)
    assert paused.status is RunStatus.WAITING_APPROVAL
    resumed = transition(paused, RunStatus.RUNNING)
    assert resumed.status is RunStatus.RUNNING

    cancelling = transition(resumed, RunStatus.CANCELLING)
    cancelled = transition(cancelling, RunStatus.CANCELLED)
    assert cancelled.status is RunStatus.CANCELLED
    with pytest.raises(InvalidTransition):
        transition(cancelled, RunStatus.RUNNING)


def test_run_state_machine_rejects_stale_version():
    snap = RunSnapshot(run_id="run_1", status=RunStatus.QUEUED, version=2)
    with pytest.raises(ValueError, match="Stale run snapshot"):
        transition(snap, RunStatus.RUNNING, expected_version=1)


def test_event_envelope_round_trip_and_validation():
    event = new_event(
        RUN_COMPLETED,
        tenant_id="org_1",
        workspace_id="ws_1",
        run_id="run_1",
        payload={"status": "success"},
    )
    restored = EventEnvelope.from_dict(event.to_dict())
    assert restored == event
    assert restored.schema_version == 1
    with pytest.raises(ValueError, match="Unknown event type"):
        new_event("run.unknown", tenant_id="org_1")
    with pytest.raises(ValueError, match="tenant_id"):
        new_event(RUN_COMPLETED, tenant_id="")


def test_event_bus_delivers_to_specific_and_wildcard_handlers():
    import asyncio

    bus = InMemoryEventBus()
    seen: list[str] = []
    bus.subscribe(RUN_COMPLETED, lambda event: seen.append(f"specific:{event.event_id}"))
    bus.subscribe("*", lambda event: seen.append(f"all:{event.event_id}"))
    event = new_event(RUN_COMPLETED, tenant_id="org_1")
    asyncio.run(bus.publish(event))
    assert seen == [f"specific:{event.event_id}", f"all:{event.event_id}"]


def test_idempotency_key_is_stable_and_attempt_scoped():
    first = idempotency_key("run_1", "node_1", "send_email", attempt=0)
    retry = idempotency_key("run_1", "node_1", "send_email", attempt=0)
    second = idempotency_key("run_1", "node_1", "send_email", attempt=1)
    assert first == retry
    assert first != second


def test_registry_covers_every_native_tool_with_risk_metadata():
    from app.ai.tools import TOOLS

    registry = ToolRegistry.from_native_tools()
    assert set(registry.names()) == set(TOOLS)
    for descriptor in registry.list():
        assert descriptor.risk_class in set(RiskClass)
        assert descriptor.idempotency in set(Idempotency)
        assert descriptor.timeout_s > 0
        assert descriptor.max_output_bytes > 0


def test_gateway_allows_read_only_with_capability_and_invokes_runner():
    called: list[tuple[str, dict]] = []

    def runner(ctx, name, args):
        called.append((name, args))
        return "ok"

    gateway = ToolGateway(ToolRegistry.from_native_tools(), runner=runner)
    result = await_invoke(
        gateway,
        ToolInvocation(
            run_id="run_1",
            node_id="agent_1",
            tool_name="current_time",
            arguments={},
            idempotency_key="run_1:agent_1:current_time:0",
        ),
        capabilities=frozenset({"tool:current_time:invoke"}),
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert result.output == "ok"
    assert called == [("current_time", {})]


def test_gateway_denies_missing_capability():
    gateway = ToolGateway(ToolRegistry.from_native_tools(), runner=lambda *args: "no")
    result = await_invoke(
        gateway,
        ToolInvocation(
            run_id="run_1",
            node_id="agent_1",
            tool_name="current_time",
            arguments={},
            idempotency_key="run_1:agent_1:current_time:0",
        ),
        capabilities=frozenset(),
    )
    assert result.status is ToolResultStatus.DENIED
    assert result.error_code == "CAPABILITY_MISSING"


def test_gateway_requires_approval_for_write_and_allows_with_grant():
    gateway = ToolGateway(ToolRegistry.from_native_tools(), runner=lambda *args: "written")
    invocation = ToolInvocation(
        run_id="run_1",
        node_id="agent_1",
        tool_name="datatable_insert_row",
        arguments={"table_id": "dt_1", "data": {"x": 1}},
        idempotency_key="run_1:agent_1:datatable_insert_row:0",
    )
    denied = await_invoke(
        gateway,
        invocation,
        capabilities=frozenset({"tool:datatable_insert_row:invoke"}),
    )
    assert denied.status is ToolResultStatus.APPROVAL_REQUIRED
    assert denied.error_code == "APPROVAL_REQUIRED"

    allowed = await_invoke(
        gateway,
        invocation,
        capabilities=frozenset({"tool:datatable_insert_row:invoke"}),
        approval_granted=True,
    )
    assert allowed.status is ToolResultStatus.SUCCESS
    assert allowed.output == "written"


def test_gateway_rejects_unknown_tool_and_normalizes_runner_errors():
    gateway = ToolGateway(ToolRegistry.from_native_tools(), runner=lambda *args: (_ for _ in ()).throw(RuntimeError("boom")))
    unknown = await_invoke(
        gateway,
        ToolInvocation(
            run_id="run_1",
            node_id="agent_1",
            tool_name="not_real",
            arguments={},
            idempotency_key="run_1:agent_1:not_real:0",
        ),
        capabilities=frozenset({"tool:*:invoke"}),
    )
    assert unknown.status is ToolResultStatus.DENIED
    assert unknown.error_code == "UNKNOWN_TOOL"

    failed = await_invoke(
        gateway,
        ToolInvocation(
            run_id="run_1",
            node_id="agent_1",
            tool_name="current_time",
            arguments={},
            idempotency_key="run_1:agent_1:current_time:0",
        ),
        capabilities=frozenset({"tool:current_time:invoke"}),
    )
    assert failed.status is ToolResultStatus.ERROR
    assert failed.error_code == "RuntimeError"


def test_new_platform_modules_do_not_import_the_api_layer():
    root = Path(__file__).resolve().parents[1] / "app"
    for relative in ("platform", "orchestration", "tools"):
        for path in (root / relative).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "from app.api" not in source, path
            assert "import app.api" not in source, path


def test_checkpoint_carries_run_node_and_version():
    checkpoint = Checkpoint(
        run_id="run_1",
        node_id="node_1",
        status="success",
        outputs={"main": [{"x": 1}]},
        version=3,
    )
    assert checkpoint.run_id == "run_1"
    assert checkpoint.outputs["main"] == [{"x": 1}]


def test_agent_tool_execution_default_path_delegates(monkeypatch):
    import asyncio

    from app.agents import tool_execution

    async def fake_run_tool(ctx, name, args):
        return "ok"

    monkeypatch.setattr("app.ai.tools.run_tool", fake_run_tool)
    result = asyncio.run(
        tool_execution.execute_tool(None, "current_time", {}, policy_enabled=False)
    )
    assert result == "ok"


def test_agent_tool_execution_policy_blocks_write_tools():
    import asyncio
    import json

    from app.agents.tool_execution import execute_tool
    from app.platform.contracts import ToolResult, ToolResultStatus

    class Gateway:
        async def invoke(self, invocation, *, capabilities, approval_granted=False):
            assert "tool:datatable_insert_row:invoke" in capabilities
            return ToolResult(
                tool_name=invocation.tool_name,
                status=ToolResultStatus.APPROVAL_REQUIRED,
                error_code="APPROVAL_REQUIRED",
            )

    payload = json.loads(
        asyncio.run(
            execute_tool(
                None,
                "datatable_insert_row",
                {"x": 1},
                declared_tools=["datatable_insert_row"],
                gateway=Gateway(),
                policy_enabled=True,
            )
        )
    )
    assert payload["status"] == "pending_approval"
    assert payload["tool"] == "datatable_insert_row"


def test_agent_tool_execution_policy_denies_and_allows():
    import asyncio
    import json

    from app.agents.tool_execution import execute_tool
    from app.platform.contracts import ToolResult, ToolResultStatus

    class Gateway:
        def __init__(self, status):
            self.status = status

        async def invoke(self, invocation, *, capabilities, approval_granted=False):
            return ToolResult(
                tool_name=invocation.tool_name,
                status=self.status,
                output="done" if self.status is ToolResultStatus.SUCCESS else None,
                error_code="CAPABILITY_MISSING"
                if self.status is ToolResultStatus.DENIED
                else None,
            )

    denied = json.loads(
        asyncio.run(
            execute_tool(
                None,
                "current_time",
                {},
                declared_tools=["current_time"],
                gateway=Gateway(ToolResultStatus.DENIED),
                policy_enabled=True,
            )
        )
    )
    assert denied["status"] == "denied"

    allowed = asyncio.run(
        execute_tool(
            None,
            "current_time",
            {},
            declared_tools=["current_time"],
            gateway=Gateway(ToolResultStatus.SUCCESS),
            policy_enabled=True,
        )
    )
    assert allowed == "done"


def test_run_coordinator_lifecycle_and_idempotent_start():
    import asyncio

    async def scenario():
        store = InMemoryRunStore()
        queue = InMemoryJobQueue()
        bus = InMemoryEventBus()
        coordinator = RunCoordinator(store, queue, bus)
        command = StartRun(
            run_id="run_1",
            workflow_id="wf_1",
            tenant_id="org_1",
            workspace_id="ws_1",
            payload={"x": 1},
        )

        started = await coordinator.start(command)
        assert started.status is RunStatus.QUEUED
        assert started.version == 0
        again = await coordinator.start(command)
        assert again == started
        assert len(queue._jobs) == 1

        running = await coordinator.claim("run_1", "worker_1")
        assert running.status is RunStatus.RUNNING
        paused = await coordinator.pause("run_1", "manual review")
        assert paused.status is RunStatus.WAITING_APPROVAL
        resumed = await coordinator.resume("run_1")
        assert resumed.status is RunStatus.RUNNING
        finished = await coordinator.finish("run_1", RunStatus.SUCCESS)
        assert finished.status is RunStatus.SUCCESS

        event_types = [event.event_type for event in bus.history()]
        assert event_types == [
            "run.queued",
            "run.started",
            "run.paused",
            "run.resumed",
            "run.completed",
        ]
        assert bus.history()[-1].payload["status"] == "success"

    asyncio.run(scenario())


def test_run_coordinator_cancel_path_and_checkpoint():
    import asyncio

    async def scenario():
        store = InMemoryRunStore()
        queue = InMemoryJobQueue()
        coordinator = RunCoordinator(store, queue)
        await coordinator.start(
            StartRun(run_id="run_2", workflow_id="wf_2", tenant_id="org_1")
        )
        await coordinator.claim("run_2", "worker_1")
        cancelling = await coordinator.request_cancel("run_2")
        assert cancelling.status is RunStatus.CANCELLING
        cancelled = await coordinator.confirm_cancel("run_2")
        assert cancelled.status is RunStatus.CANCELLED

        await coordinator.save_checkpoint(
            Checkpoint(
                run_id="run_2",
                node_id="node_1",
                status="success",
                outputs={"main": []},
                version=2,
            )
        )
        assert len(store.checkpoints("run_2")) == 1
        with pytest.raises(ValueError, match="terminal status"):
            await coordinator.finish("run_2", RunStatus.RUNNING)

    asyncio.run(scenario())


def await_invoke(gateway: ToolGateway, invocation: ToolInvocation, **kwargs):
    import asyncio

    return asyncio.run(gateway.invoke(invocation, **kwargs))
