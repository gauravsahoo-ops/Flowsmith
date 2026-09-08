"""Phase 23 tests: connector/engine integration.

Verifies that when a connector is registered for a node type, the engine
routes execution through the connector's op_execute() instead of the node
class's run().
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.connectors import (
    ConnectorCategory,
    ConnectorDefinitionV1,
    ConnectorErrorCode,
    ConnectorError,
    ConnectorHealthCheck,
    ConnectorLifecycle,
    ConnectorSDK,
    make_connector_error,
)
from app.connectors.registry import ConnectorRegistry
from app.engine.executor import execute_workflow
from app.engine.node_base import NodeResult
from app.schemas.workflow import Connection, WorkflowNode, Workflow
from tests.conftest import conn, make_node, make_workflow


class StubConnector(ConnectorSDK):
    """A test connector that returns controlled results."""

    connector_id = "stub"
    display_name = "Stub Connector"
    description = "Test-only connector"
    version = "1.0.0"
    category = ConnectorCategory.TRANSFORM

    def __init__(self, result: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._result = result or {"output": {"via": "connector"}, "success": True}
        self._error = error
        self._calls: list[tuple[str, dict, dict | None]] = []

    @property
    def node_types(self) -> list[str]:
        return ["stub_action"]

    async def op_execute(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        self._calls.append((operation, payload, context))
        if self._error is not None:
            raise self._error
        return self._result

    async def op_health_check(self) -> ConnectorHealthCheck:
        return ConnectorHealthCheck(healthy=True, message="ok")


def _make_stub_defn() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key="stub",
        display_name="Stub Connector",
        description="Test-only connector",
        category="transform",
        connector_version="1.0.0",
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={},
        triggers={},
        credential_types={},
    )


@pytest.fixture()
def stub_registry():
    """Provide a fresh ConnectorRegistry with a stub connector."""
    registry = ConnectorRegistry()
    registry.initialize()
    connector = StubConnector()
    registry.register(connector, _make_stub_defn())
    return registry, connector


def _make_node_with_creds(
    node_id: str,
    node_type: str,
    parameters: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    credentials: dict[str, str] | None = None,
) -> WorkflowNode:
    """Helper that supports credentials (conftest.make_node doesn't)."""
    return WorkflowNode(
        id=node_id,
        type=node_type,
        parameters=parameters or {},
        settings=settings or {},
        credentials=credentials or {},
    )


@pytest.mark.asyncio
async def test_connector_routes_execution(stub_registry):
    """When a connector is registered for the node type, the engine
    routes through connector.op_execute() instead of the node class."""
    registry, connector = stub_registry
    with patch("app.engine.executor.get_connector_registry", return_value=registry), \
         patch("app.connectors.get_registry", return_value=registry):
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"), make_node("act", "stub_action")],
            [conn("trigger", "act")],
        )
        result = await execute_workflow(wf, [{"data": "input"}])

    assert result.status == "success"
    assert "act" in result.results
    assert result.results["act"]["main"][0]["via"] == "connector"
    assert len(connector._calls) == 1
    assert connector._calls[0][0] == "execute"


@pytest.mark.asyncio
async def test_connector_receives_credentials(stub_registry):
    """The connector receives resolved credentials in its context."""
    registry, connector = stub_registry
    with patch("app.engine.executor.get_connector_registry", return_value=registry), \
         patch("app.connectors.get_registry", return_value=registry):
        node_trigger = make_node("trigger", "manual_trigger")
        node_act = _make_node_with_creds("act", "stub_action", credentials={"http": "cred_123"})
        wf = Workflow(
            id="wf_cred", name="cred test",
            nodes=[node_trigger, node_act],
            connections=[conn("trigger", "act")],
        )
        result = await execute_workflow(
            wf, [{"data": "input"}],
            credential_resolver=lambda creds: {"http": {"api_key": "secret"}},
        )

    assert result.status == "success"
    ctx = connector._calls[0][2]
    assert ctx["credentials"]["http"]["api_key"] == "secret"


@pytest.mark.asyncio
async def test_connector_error_retries(stub_registry):
    """Connector errors that are retryable trigger retry logic."""
    registry, connector = stub_registry
    connector._error = make_connector_error(ConnectorErrorCode.TIMEOUT, "timed out", retryable=True)

    with patch("app.engine.executor.get_connector_registry", return_value=registry), \
         patch("app.connectors.get_registry", return_value=registry):
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             make_node("act", "stub_action", settings={"retry_max_attempts": 2, "retry_backoff_seconds": 0.01})],
            [conn("trigger", "act")],
        )
        result = await execute_workflow(wf, [{}])

    assert result.status == "failed"
    assert "act" in result.node_errors


@pytest.mark.asyncio
async def test_connector_error_not_retryable(stub_registry):
    """Non-retryable connector errors fail immediately."""
    registry, connector = stub_registry
    connector._error = make_connector_error(ConnectorErrorCode.BAD_REQUEST, "bad request", retryable=False)

    with patch("app.engine.executor.get_connector_registry", return_value=registry), \
         patch("app.connectors.get_registry", return_value=registry):
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"), make_node("act", "stub_action")],
            [conn("trigger", "act")],
        )
        result = await execute_workflow(wf, [{}])

    assert result.status == "failed"
    assert result.node_errors["act"].code == "CONNECTOR_BAD_REQUEST"


@pytest.mark.asyncio
async def test_no_connector_falls_back_to_node():
    """When no connector is registered, the engine uses the node class."""
    empty_registry = ConnectorRegistry()
    empty_registry.initialize()
    with patch("app.engine.executor.get_connector_registry", return_value=empty_registry), \
         patch("app.connectors.get_registry", return_value=empty_registry):
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"), make_node("set", "set_data", parameters={"fields": {"x": 1}})],
            [conn("trigger", "set")],
        )
        result = await execute_workflow(wf, [{"y": 2}])

    assert result.status == "success"
    assert result.results["set"]["main"] == [{"y": 2, "x": 1}]


@pytest.mark.asyncio
async def test_connector_receives_resolved_params(stub_registry):
    """The connector receives the Pydantic-validated parameters as its payload."""
    registry, connector = stub_registry
    with patch("app.engine.executor.get_connector_registry", return_value=registry), \
         patch("app.connectors.get_registry", return_value=registry):
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             make_node("act", "stub_action", parameters={"method": "GET", "url": "https://example.com"})],
            [conn("trigger", "act")],
        )
        result = await execute_workflow(wf, [{}])

    assert result.status == "success"
    payload = connector._calls[0][1]
    assert payload["method"] == "GET"
    assert payload["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_connector_trace_recorded(stub_registry):
    """Execution trace includes connector info in the step note."""
    registry, connector = stub_registry
    with patch("app.engine.executor.get_connector_registry", return_value=registry), \
         patch("app.connectors.get_registry", return_value=registry):
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"), make_node("act", "stub_action")],
            [conn("trigger", "act")],
        )
        result = await execute_workflow(wf, [{}])

    act_step = [s for s in result.trace if s["node_id"] == "act"][0]
    assert act_step["status"] == "success"
    assert "stub" in act_step["note"]
