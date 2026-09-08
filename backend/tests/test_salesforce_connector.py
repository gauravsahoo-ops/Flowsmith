"""Salesforce connector tests: token flow, REST ops, error mapping, engine routing."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.connectors import (
    ConnectorErrorCode,
    get_registry,
    make_connector_error,
)
from app.connectors.salesforce_connector import SalesforceConnector
from app.engine.executor import execute_workflow
from app.schemas.workflow import Workflow, WorkflowNode
from tests.conftest import conn, make_node, make_workflow


class FakeSFHTTPClient:
    """Replaces SafeHTTPClient: scripted responses for token + data API."""

    def __init__(self, responses: list[tuple[httpx.Response, dict[str, Any] | None]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        self.calls.append((method, url, {"params": params, "json": json, "data": data, "headers": headers}))
        response, _expected = self.responses.pop(0)
        return response


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_client(responses: list[tuple[httpx.Response, dict[str, Any] | None]]):
    fake = FakeSFHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.salesforce.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


CREDS = {
    "salesforce": {
        "instance_url": "https://login.salesforce.com",
        "client_id": "cid",
        "client_secret": "csecret",
        "username": "user@example.com",
        "password": "pass+token",
        "api_version": "v63.0",
    }
}


def _reset_registry() -> None:
    registry = get_registry()
    registry.initialize()
    from app.connectors import register_builtin_connectors

    register_builtin_connectors()


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry()
    yield
    _reset_registry()


@pytest.fixture
def connector() -> SalesforceConnector:
    conn_inst = get_registry().get("salesforce")
    assert isinstance(conn_inst, SalesforceConnector)
    return conn_inst


async def test_token_fetch_and_query(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    query_response = _json_response(200, {"totalSize": 2, "done": True, "records": [{"Id": "a", "Name": "A"}, {"Id": "b", "Name": "B"}]})
    patcher, fake = _patch_client([(token_response, None), (query_response, None)])
    try:
        result = await connector.op_execute("execute", {
            "operation": "query",
            "soql": "SELECT Id, Name FROM Account",
        }, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert result["success"] is True
    assert result["output"]["totalSize"] == 2
    assert [r["Name"] for r in result["output"]["records"]] == ["A", "B"]

    token_call = fake.calls[0]
    assert token_call[0] == "POST"
    assert token_call[1] == "https://login.salesforce.com/services/oauth2/token"
    assert token_call[2]["data"] is not None
    assert "client_secret=csecret" in token_call[2]["data"]
    assert token_call[2]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    query_call = fake.calls[1]
    assert query_call[1] == "https://myorg.salesforce.com/services/data/v63.0/query"
    assert query_call[2]["headers"]["Authorization"] == "Bearer tok123"


async def test_token_cached_between_calls(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    q1 = _json_response(200, {"totalSize": 0, "done": True, "records": []})
    q2 = _json_response(200, {"totalSize": 0, "done": True, "records": []})
    patcher, fake = _patch_client([(token_response, None), (q1, None), (q2, None)])
    try:
        await connector.op_execute("execute", {"operation": "query", "soql": "SELECT Id FROM Account"}, {"credentials": CREDS})
        await connector.op_execute("execute", {"operation": "query", "soql": "SELECT Id FROM Contact"}, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert sum(1 for m, url, _ in fake.calls if url.endswith("/services/oauth2/token")) == 1
    assert len(fake.calls) == 3


async def test_auth_failure_maps_to_connector_error(connector: SalesforceConnector) -> None:
    token_response = httpx.Response(401, json=[{"message": "invalid_grant"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {"operation": "query", "soql": "SELECT Id FROM Account"}, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.AUTH_FAILED.value
    assert getattr(excinfo.value, "retryable", None) is False


async def test_rate_limit_maps_to_retryable_error(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    limited = httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None), (limited, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {"operation": "query", "soql": "SELECT Id FROM Account"}, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.RATE_LIMITED.value
    assert getattr(excinfo.value, "retryable", None) is True


async def test_operation_name_comes_from_payload(connector: SalesforceConnector) -> None:
    """The engine calls op_execute('execute', ...); the real operation
    must come from the payload's operation field."""
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    create_response = _json_response(201, {"id": "001abc", "success": True})
    patcher, fake = _patch_client([(token_response, None), (create_response, None)])
    try:
        result = await connector.op_execute("execute", {
            "operation": "create",
            "object_name": "Account",
            "record": {"Name": "Acme"},
        }, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert result["success"] is True
    assert result["output"]["id"] == "001abc"
    create_call = fake.calls[1]
    assert create_call[1] == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Account"
    assert create_call[2]["json"] == {"Name": "Acme"}


async def test_unknown_operation_rejected(connector: SalesforceConnector) -> None:
    with pytest.raises(Exception) as excinfo:
        await connector.op_execute("execute", {"operation": "explode"}, {"credentials": CREDS})
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value


# ----------------------------------------------------------------------
# Search/Get Record (Phase 8)
# ----------------------------------------------------------------------


async def test_search_found_normalizes_response(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    search_response = _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc"}]})
    record_response = _json_response(200, {"Id": "00Qabc", "Name": "Jane", "Email": "jane@example.com", "Company": "Acme"})
    patcher, fake = _patch_client([(token_response, None), (search_response, None), (record_response, None)])
    try:
        result = await connector.op_execute("execute", {
            "operation": "search",
            "object_name": "Lead",
            "search_field": "Email",
            "search_value": "jane@example.com",
        }, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert result["success"] is True
    assert result["operation"] == "search"
    assert result["output"]["found"] is True
    assert result["output"]["record"]["Id"] == "00Qabc"
    assert result["output"]["record"]["Email"] == "jane@example.com"
    assert result["output"]["object_name"] == "Lead"
    assert result["output"]["search_field"] == "Email"

    # The search uses a bounded SOQL query on the search field.
    method, url, kwargs = fake.calls[1]
    assert method == "GET"
    assert url == "https://myorg.salesforce.com/services/data/v63.0/query"
    assert kwargs["params"]["q"] == "SELECT Id FROM Lead WHERE Email = 'jane@example.com' LIMIT 1"
    # The full record is fetched by id.
    assert fake.calls[2][1] == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Lead/00Qabc"


async def test_search_not_found_returns_normalized_result(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    empty_response = _json_response(200, {"totalSize": 0, "done": True, "records": []})
    patcher, fake = _patch_client([(token_response, None), (empty_response, None)])
    try:
        result = await connector.op_execute("execute", {
            "operation": "search",
            "object_name": "Lead",
            "search_field": "Email",
            "search_value": "nobody@example.com",
        }, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert result["success"] is True
    assert result["output"]["found"] is False
    assert result["output"]["record"] is None
    assert len(fake.calls) == 2  # no record fetch when nothing matched


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({"operation": "search", "search_field": "Email", "search_value": "x"}, "object name"),
        ({"operation": "search", "object_name": "Lead; DROP", "search_field": "Email", "search_value": "x"}, "object name"),
        ({"operation": "search", "object_name": "Lead", "search_value": "x"}, "search field"),
        ({"operation": "search", "object_name": "Lead", "search_field": "Email; DROP", "search_value": "x"}, "search field"),
        ({"operation": "search", "object_name": "Lead", "search_field": "Email", "search_value": ""}, "search value"),
        ({"operation": "search", "object_name": "Lead", "search_field": "Email"}, "search value"),
    ],
)
async def test_search_invalid_input_rejected(connector: SalesforceConnector, payload: dict, fragment: str) -> None:
    with pytest.raises(Exception) as excinfo:
        await connector.op_execute("execute", payload, {"credentials": CREDS})
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value
    assert getattr(excinfo.value, "retryable", None) is False
    assert fragment in str(excinfo.value)


async def test_search_auth_failure_maps_to_typed_error(connector: SalesforceConnector) -> None:
    token_response = httpx.Response(401, json=[{"message": "invalid_grant"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "search",
                "object_name": "Lead",
                "search_field": "Email",
                "search_value": "jane@example.com",
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.AUTH_FAILED.value
    assert getattr(excinfo.value, "retryable", None) is False


async def test_search_api_failure_maps_to_typed_error(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    api_error = httpx.Response(500, json=[{"message": "Internal Server Error"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None), (api_error, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "search",
                "object_name": "Lead",
                "search_field": "Email",
                "search_value": "jane@example.com",
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.UNAVAILABLE.value
    assert getattr(excinfo.value, "retryable", None) is True


# ----------------------------------------------------------------------
# Update Record (Phase 10)
# ----------------------------------------------------------------------

SF_ID_15 = "00Qabcdefgh1234"  # valid 15-char Salesforce id
SF_ID_18 = "00Qabcdefgh1234abc"  # valid 18-char (15 + 3-char suffix)


async def test_update_success_normalizes_response(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    update_response = httpx.Response(204, request=httpx.Request("GET", "http://fake"))
    patcher, fake = _patch_client([(token_response, None), (update_response, None)])
    try:
        result = await connector.op_execute("execute", {
            "operation": "update",
            "object_name": "Lead",
            "record_id": SF_ID_15,
            "record": {"Company": "Updated Company"},
        }, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert result["success"] is True
    assert result["operation"] == "update"
    assert result["output"] == {"id": SF_ID_15, "success": True}
    _method, url, kwargs = fake.calls[1]
    assert url == f"https://myorg.salesforce.com/services/data/v63.0/sobjects/Lead/{SF_ID_15}"
    assert kwargs["json"] == {"Company": "Updated Company"}


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({"operation": "update", "object_name": "Lead", "record": {"Company": "X"}}, "record id"),
        ({"operation": "update", "object_name": "Lead", "record_id": "", "record": {"Company": "X"}}, "record id"),
        ({"operation": "update", "object_name": "Lead", "record_id": "001", "record": {"Company": "X"}}, "record id"),
        ({"operation": "update", "object_name": "Lead", "record_id": "NOT VALID!!!", "record": {"Company": "X"}}, "record id"),
        ({"operation": "update", "object_name": "Lead", "record_id": SF_ID_15, "record": {}}, "fields object"),
        ({"operation": "update", "object_name": "Lead", "record_id": SF_ID_15, "record": ["Company"]}, "valid dict"),
        ({"operation": "update", "object_name": "Lead", "record_id": SF_ID_15}, "fields object"),
        ({"operation": "update", "object_name": "Lead", "record_id": SF_ID_15, "record": {"Bad Field": "x"}}, "field name"),
        ({"operation": "update", "object_name": "Lead", "record_id": SF_ID_15, "record": {"Nested": {"a": 1}}}, "scalar"),
        ({"operation": "update", "object_name": "Lead", "record_id": SF_ID_15, "record": {"Tags": ["a"]}}, "scalar"),
    ],
)
async def test_update_invalid_input_rejected(connector: SalesforceConnector, payload: dict, fragment: str) -> None:
    with pytest.raises(Exception) as excinfo:
        await connector.op_execute("execute", payload, {"credentials": CREDS})
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value
    assert getattr(excinfo.value, "retryable", None) is False
    assert fragment in str(excinfo.value)


async def test_update_accepts_18_char_id(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    update_response = httpx.Response(204, request=httpx.Request("GET", "http://fake"))
    patcher, fake = _patch_client([(token_response, None), (update_response, None)])
    try:
        result = await connector.op_execute("execute", {
            "operation": "update",
            "object_name": "Lead",
            "record_id": SF_ID_18,
            "record": {"Company": "Updated Company"},
        }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert result["output"]["id"] == SF_ID_18
    assert fake.calls[1][1].endswith(f"/sobjects/Lead/{SF_ID_18}")


async def test_update_auth_failure_is_typed(connector: SalesforceConnector) -> None:
    token_response = httpx.Response(401, json=[{"message": "invalid_grant"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "update",
                "object_name": "Lead",
                "record_id": SF_ID_15,
                "record": {"Company": "X"},
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.AUTH_FAILED.value
    assert getattr(excinfo.value, "retryable", None) is False


async def test_update_not_found_maps_to_typed_error(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    api_error = httpx.Response(404, json=[{"message": "The requested resource does not exist"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None), (api_error, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "update",
                "object_name": "Lead",
                "record_id": SF_ID_15,
                "record": {"Company": "X"},
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.NOT_FOUND.value
    assert getattr(excinfo.value, "retryable", None) is False


async def test_update_rate_limited_stays_retryable(connector: SalesforceConnector) -> None:
    """Update is idempotent: a 429 keeps retryable=True (unlike create)."""
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    limited = httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None), (limited, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "update",
                "object_name": "Lead",
                "record_id": SF_ID_15,
                "record": {"Company": "X"},
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.RATE_LIMITED.value
    assert getattr(excinfo.value, "retryable", None) is True


async def test_engine_retries_update_on_429(connector: SalesforceConnector) -> None:
    """An idempotent update retries on 429 and succeeds."""
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    limited = httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake"))
    ok_response = httpx.Response(204, request=httpx.Request("GET", "http://fake"))
    patcher, fake = _patch_client([(token_response, None), (limited, None), (ok_response, None)])
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             WorkflowNode(
                 id="sf", type="salesforce",
                 parameters={"operation": "update", "object_name": "Lead",
                             "record_id": SF_ID_15, "record": {"Company": "Updated Company"}},
                 settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0.01},
                 credentials={"salesforce": "cred_1"},
             )],
            [conn("trigger", "sf")],
        )
        result = await execute_workflow(wf, [{}], credential_resolver=lambda refs: {"salesforce": CREDS["salesforce"]})
    finally:
        patcher.stop()

    assert result.status == "success"
    assert result.results["sf"]["main"][0]["id"] == SF_ID_15
    assert len(fake.calls) == 3  # token + failed attempt + retried attempt


# ----------------------------------------------------------------------
# Phase 11: Salesforce inside a full DAG
# ----------------------------------------------------------------------


async def test_engine_full_dag_search_maps_between_nodes() -> None:
    """Manual Trigger -> Set Data -> Salesforce Search -> Set Data.

    Verifies data mapping into the Salesforce node, its output, and the
    next node's input through the generic DAG execution path (no special
    Salesforce path).
    """
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    search_response = _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc123"}]})
    record_response = _json_response(200, {"Id": "00Qabc123", "Name": "Jane Doe", "Email": "jane@example.com", "Company": "Acme"})
    patcher, fake = _patch_client([(token_response, None), (search_response, None), (record_response, None)])
    try:
        wf = make_workflow(
            [
                make_node("trigger", "manual_trigger"),
                make_node("sd1", "set_data", {"fields": {"email": "{{ $json.email }}"}}),
                WorkflowNode(
                    id="sf", type="salesforce",
                    parameters={
                        "operation": "search",
                        "object_name": "Lead",
                        "search_field": "Email",
                        "search_value": "{{ $node.sd1.json.email }}",
                    },
                    settings={}, credentials={"salesforce": "cred_1"},
                ),
                make_node("sd2", "set_data", {
                    "fields": {
                        "lead_email": "{{ $node.sf.json.record.Email }}",
                        "lead_name": "{{ $node.sf.json.record.Name }}",
                        "found": "{{ $node.sf.json.found }}",
                    }
                }),
            ],
            [conn("trigger", "sd1"), conn("sd1", "sf"), conn("sf", "sd2")],
            wf_id="wf_dag_sf",
        )
        result = await execute_workflow(
            wf, [{"email": "jane@example.com"}],
            credential_resolver=lambda refs: {"salesforce": CREDS["salesforce"]},
        )
    finally:
        patcher.stop()

    # The whole DAG ran.
    assert result.status == "success"
    assert set(result.results) == {"trigger", "sd1", "sf", "sd2"}
    assert result.node_errors == {}

    # Data mapping: set_data output fed the Salesforce search input.
    search_call = fake.calls[1]
    assert search_call[2]["params"]["q"] == "SELECT Id FROM Lead WHERE Email = 'jane@example.com' LIMIT 1"

    # Salesforce node output.
    sf_output = result.results["sf"]["main"][0]
    assert sf_output["found"] is True
    assert sf_output["record"]["Email"] == "jane@example.com"

    # Next-node input: the final set_data consumed the Salesforce output.
    assert result.results["sd2"]["main"][0] == {
        **sf_output,
        "lead_email": "jane@example.com",
        "lead_name": "Jane Doe",
    }

    # Trace covers the chain in order.
    trace_ids = [step["node_id"] for step in result.trace]
    assert trace_ids == ["trigger", "sd1", "sf", "sd2"]
    assert any(step["node_id"] == "sf" and step["status"] == "success" for step in result.trace)


# ----------------------------------------------------------------------
# Create Record (Phase 9)
# ----------------------------------------------------------------------


async def test_create_success_normalizes_response(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    create_response = _json_response(201, {"id": "00Qnew123", "success": True})
    patcher, fake = _patch_client([(token_response, None), (create_response, None)])
    try:
        result = await connector.op_execute("execute", {
            "operation": "create",
            "object_name": "Lead",
            "record": {"FirstName": "Automation", "LastName": "Test", "Company": "Test Company", "Email": "test@example.com"},
        }, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert result["success"] is True
    assert result["operation"] == "create"
    assert result["output"]["id"] == "00Qnew123"
    assert result["output"]["success"] is True
    _method, url, kwargs = fake.calls[1]
    assert url == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Lead"
    assert kwargs["json"]["FirstName"] == "Automation"
    assert kwargs["json"]["Email"] == "test@example.com"


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({"operation": "create", "record": {"Name": "Acme"}}, "object name"),
        ({"operation": "create", "object_name": "Lead; DROP", "record": {"Name": "Acme"}}, "object name"),
        ({"operation": "create", "object_name": "Lead", "record": {}}, "record object"),
        ({"operation": "create", "object_name": "Lead", "record": ["Name"]}, "valid dict"),
        ({"operation": "create", "object_name": "Lead"}, "record object"),
        ({"operation": "create", "object_name": "Lead", "record": {"Name; DROP": "x"}}, "field name"),
        ({"operation": "create", "object_name": "Lead", "record": {"Nested": {"a": 1}}}, "scalar"),
        ({"operation": "create", "object_name": "Lead", "record": {"Tags": ["a"]}}, "scalar"),
    ],
)
async def test_create_invalid_input_rejected(connector: SalesforceConnector, payload: dict, fragment: str) -> None:
    with pytest.raises(Exception) as excinfo:
        await connector.op_execute("execute", payload, {"credentials": CREDS})
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value
    assert getattr(excinfo.value, "retryable", None) is False
    assert fragment in str(excinfo.value)


async def test_create_auth_failure_is_typed_and_non_retryable(connector: SalesforceConnector) -> None:
    token_response = httpx.Response(401, json=[{"message": "invalid_grant"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "create",
                "object_name": "Lead",
                "record": {"Email": "test@example.com"},
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.AUTH_FAILED.value
    assert getattr(excinfo.value, "retryable", None) is False


async def test_create_api_failure_preserves_message_and_is_non_retryable(connector: SalesforceConnector) -> None:
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    api_error = httpx.Response(400, json=[{"message": "INVALID_FIELD_FOR_INSERT_UPDATE: Email"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None), (api_error, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "create",
                "object_name": "Lead",
                "record": {"Email": "not-an-email"},
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value
    assert getattr(excinfo.value, "retryable", None) is False
    assert "INVALID_FIELD_FOR_INSERT_UPDATE" in str(excinfo.value)


async def test_create_rate_limited_is_not_retryable(connector: SalesforceConnector) -> None:
    """Phase 9: never auto-retry create - a retry may duplicate the record."""
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    limited = httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([(token_response, None), (limited, None)])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "create",
                "object_name": "Lead",
                "record": {"Email": "test@example.com"},
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.RATE_LIMITED.value
    assert getattr(excinfo.value, "retryable", None) is False  # downgraded from provider


async def test_engine_never_retries_create(connector: SalesforceConnector) -> None:
    """Even with retry settings, a failed create runs exactly once."""
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    limited = httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake"))
    patcher, fake = _patch_client([(token_response, None), (limited, None)])
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             WorkflowNode(
                 id="sf", type="salesforce",
                 parameters={"operation": "create", "object_name": "Lead", "record": {"Email": "test@example.com"}},
                 settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0.01},
                 credentials={"salesforce": "cred_1"},
             )],
            [conn("trigger", "sf")],
        )
        result = await execute_workflow(wf, [{}], credential_resolver=lambda refs: {"salesforce": CREDS["salesforce"]})
    finally:
        patcher.stop()

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "CONNECTOR_RATE_LIMITED"
    assert result.error.retryable is False
    assert len(fake.calls) == 2  # token + exactly one create attempt, no retries


async def test_missing_credential_returns_not_configured(connector: SalesforceConnector) -> None:
    with pytest.raises(Exception) as excinfo:
        await connector.op_execute("execute", {"operation": "query", "soql": "SELECT Id FROM Account"}, {})
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.NOT_CONFIGURED.value


async def test_engine_routes_salesforce_node_to_connector() -> None:
    """A 'salesforce' node type has no node class; the engine must route
    through the registered SalesforceConnector and pass credentials."""
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    query_response = _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "001", "Name": "Acme"}]})
    patcher, fake = _patch_client([(token_response, None), (query_response, None)])
    try:
        wf = Workflow(
            id="wf_sf", name="sf test",
            nodes=[
                make_node("trigger", "manual_trigger"),
                WorkflowNode(
                    id="sf", type="salesforce",
                    parameters={"operation": "query", "soql": "SELECT Id, Name FROM Account LIMIT 1"},
                    settings={}, credentials={"salesforce": "cred_1"},
                ),
            ],
            connections=[conn("trigger", "sf")],
        )
        result = await execute_workflow(
            wf, [{"data": "input"}],
            credential_resolver=lambda refs: {"salesforce": CREDS["salesforce"]},
        )
    finally:
        patcher.stop()

    assert result.status == "success"
    assert result.results["sf"]["main"][0]["records"][0]["Name"] == "Acme"
    assert any("salesforce" in step["note"] for step in result.trace if step["node_id"] == "sf")


async def test_engine_retries_retryable_connector_error() -> None:
    """429 (rate limited) is retryable; with retry settings the run retries."""
    token_response = _json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"})
    limited = httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake"))
    ok_response = _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "001", "Name": "Acme"}]})
    patcher, fake = _patch_client([(token_response, None), (limited, None), (ok_response, None)])
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             WorkflowNode(
                 id="sf", type="salesforce",
                 parameters={"operation": "query", "soql": "SELECT Id FROM Account LIMIT 1"},
                 settings={"retry_max_attempts": 2, "retry_backoff_seconds": 0.01},
                 credentials={"salesforce": "cred_1"},
             )],
            [conn("trigger", "sf")],
        )
        result = await execute_workflow(wf, [{}], credential_resolver=lambda refs: {"salesforce": CREDS["salesforce"]})
    finally:
        patcher.stop()

    assert result.status == "success"
    assert len(fake.calls) == 3  # token + failed attempt + retry


async def test_registered_definition_populated() -> None:
    """Built-in connectors expose populated definitions (audit fix)."""
    registry = get_registry()
    defn = registry.get_definition("salesforce")
    assert defn is not None
    assert defn.operations  # non-empty
    assert defn.credential_types
    assert "salesforce" in defn.credential_types

    http_defn = registry.get_definition("http")
    assert http_defn is not None
    assert http_defn.operations
    assert "http" in http_defn.credential_types

    schedule_defn = registry.get_definition("schedule")
    assert schedule_defn is not None
    assert schedule_defn.triggers
    assert schedule_defn.triggers["cron"].trigger_type == "scheduled"

    webhook_defn = registry.get_definition("webhook")
    assert webhook_defn is not None
    assert webhook_defn.triggers
    assert webhook_defn.triggers["receive"].trigger_type == "webhook"


# ---------------------------------------------------------------------------
# Phase 9: upsert operation
# ---------------------------------------------------------------------------

_UPSERT_TOKEN = [
    (_json_response(200, {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"}), None),
]


async def test_upsert_routes_to_external_id_patch(connector: SalesforceConnector) -> None:
    patcher, fake = _patch_client([
        *_UPSERT_TOKEN,
        (_json_response(200, {"id": "001zz", "created": False}), None),
    ])
    try:
        result = await connector.op_execute("upsert", {
            "object_name": "Account",
            "external_id_field": "Legacy_Id__c",
            "external_id": "L-7",
            "record": {"Name": "Acme"},
        }, {"credentials": CREDS})
    finally:
        patcher.stop()

    assert result["success"] is True
    assert result["output"] == {"id": "001zz", "created": False, "success": True}
    method, url, kwargs = fake.calls[1]
    assert method == "PATCH"
    assert url.endswith("/sobjects/Account/Legacy_Id__c/L-7")


async def test_upsert_validation_rejects_bad_input(connector: SalesforceConnector) -> None:
    cases = [
        {},  # everything missing
        {"object_name": "Lead"},  # no external id field/value/record
        {"object_name": "Lead", "external_id_field": "Ext__c", "external_id": "E1"},  # no record
        {"object_name": "Lead", "external_id_field": "bad name!", "external_id": "E1",
         "record": {"a": 1}},  # invalid field API name
        {"object_name": "Lead", "external_id_field": "Ext__c", "external_id": "",
         "record": {"a": 1}},  # empty external id
        {"object_name": "Lead", "external_id_field": "Ext__c", "external_id": "E1",
         "record": {"nested": {"x": 1}}},  # non-scalar field
    ]
    for payload in cases:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("upsert", payload, {"credentials": CREDS})
        assert getattr(excinfo.value, "code", "") == ConnectorErrorCode.BAD_REQUEST.value, payload


async def test_upsert_is_retryable_on_rate_limit(connector: SalesforceConnector) -> None:
    """Upsert keeps provider retryability: a re-run cannot duplicate."""
    patcher, _fake = _patch_client([
        *_UPSERT_TOKEN,
        (httpx.Response(429, json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "slow"}],
                        headers={"Retry-After": "0"},
                        request=httpx.Request("GET", "http://fake")), None),
    ])
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("upsert", {
                "object_name": "Account",
                "external_id_field": "Ext__c",
                "external_id": "E1",
                "record": {"Name": "x"},
            }, {"credentials": CREDS})
    finally:
        patcher.stop()
    assert excinfo.value.code == ConnectorErrorCode.RATE_LIMITED.value
    assert excinfo.value.retryable is True


# ---------------------------------------------------------------------------
# Phase 9: bulk operation
# ---------------------------------------------------------------------------

def _bulk_scripted(state: str = "JobComplete") -> list[tuple[httpx.Response, dict | None]]:
    return [
        *_UPSERT_TOKEN,
        (_json_response(201, {"id": "job-1", "state": "Open"}), None),
        (httpx.Response(201, request=httpx.Request("PUT", "http://fake")), None),
        (_json_response(200, {"id": "job-1", "state": "UploadComplete"}), None),
        (_json_response(200, {"id": "job-1", "state": state,
                              "numberRecordsProcessed": 2,
                              "numberRecordsFailed": 0}), None),
        (httpx.Response(200, text="sf__Id,Error\n", request=httpx.Request("GET", "http://fake")), None),
        (httpx.Response(200, text="sf__Id,sf__Created\n", request=httpx.Request("GET", "http://fake")), None),
    ]


async def test_bulk_insert_via_connector(connector: SalesforceConnector) -> None:
    patcher, _fake = _patch_client(_bulk_scripted())
    try:
        result = await connector.op_execute("bulk", {
            "object_name": "Lead",
            "bulk_operation": "insert",
            "records": [{"LastName": "A"}, {"LastName": "B"}],
            "poll_interval_seconds": 0.1,
        }, {"credentials": CREDS})
    finally:
        patcher.stop()
    out = result["output"]
    assert out["state"] == "JobComplete"
    assert out["success"] is True
    assert out["records_processed"] == 2
    assert out["failed_records"] == []


async def test_bulk_validation_errors(connector: SalesforceConnector) -> None:
    base_creds = {"credentials": CREDS}
    cases = [
        {"bulk_operation": "insert", "records": [{"a": 1}]},  # bad object name
        {"object_name": "Lead", "records": [{"a": 1}]},  # missing bulk_operation -> default insert ok? default is insert; records present -> valid... adjust below
    ]
    with pytest.raises(Exception):
        await connector.op_execute("bulk", {
            "object_name": "bad name!",
            "bulk_operation": "insert",
            "records": [{"a": 1}],
        }, base_creds)
    with pytest.raises(Exception):
        await connector.op_execute("bulk", {
            "object_name": "Lead",
            "bulk_operation": "frobnicate",
            "records": [{"a": 1}],
        }, base_creds)
    with pytest.raises(Exception):
        await connector.op_execute("bulk", {
            "object_name": "Lead",
            "bulk_operation": "insert",
            "records": [],
        }, base_creds)
    with pytest.raises(Exception):
        await connector.op_execute("bulk", {
            "object_name": "Lead",
            "bulk_operation": "delete",
            "records": [{"LastName": "no-id"}],
        }, base_creds)
    with pytest.raises(Exception):
        await connector.op_execute("bulk", {
            "object_name": "Lead",
            "bulk_operation": "upsert",
            "records": [{"a": 1}],  # missing external_id_field
        }, base_creds)


async def test_bulk_insert_never_retried_by_engine() -> None:
    """A bulk-insert timeout must fail fast like create - the engine may
    not auto-retry a job that would duplicate every row."""
    from app.engine.errors import NodeExecutionError

    responses = [
        *_UPSERT_TOKEN,
        (_json_response(201, {"id": "job-dup", "state": "Open"}), None),
        (httpx.Response(201, request=httpx.Request("PUT", "http://fake")), None),
        (_json_response(200, {"id": "job-dup", "state": "UploadComplete"}), None),
        (_json_response(200, {"id": "job-dup", "state": "InProgress"}), None),  # never finishes
    ]
    patcher, _fake = _patch_client(responses)
    try:
        wf = make_workflow(
            [WorkflowNode(id="sf", type="salesforce", parameters={
                "operation": "bulk",
                "object_name": "Lead",
                "bulk_operation": "insert",
                "records": [{"LastName": "A"}],
                "poll_interval_seconds": 0.1,
                "max_polls": 2,
            }, settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0},
               credentials={"salesforce": "cred_1"})],
            wf_id="wf_bulk",
        )
        result = await execute_workflow(
            wf, [{}],
            credential_resolver=lambda refs: {"salesforce": CREDS["salesforce"]},
        )
    finally:
        patcher.stop()
    assert result.status == "failed"
    assert result.error.code in ("NODE_ERROR", "CONNECTOR_TIMEOUT", "CONNECTOR_BAD_REQUEST")
    retry_events = [e for e in result.events if e.get("event") == "node.retry"]
    assert retry_events == []


# ---------------------------------------------------------------------------
# Phase 9: describe enrichment + query pagination passthrough
# ---------------------------------------------------------------------------

async def test_describe_returns_rich_field_metadata(connector: SalesforceConnector) -> None:
    describe_body = {
        "name": "Lead", "label": "Lead", "createable": True, "updateable": True,
        "fields": [
            {"name": "Id", "label": "Lead ID", "type": "id",
             "createable": False, "updateable": False, "nillable": False},
            {"name": "Email", "label": "Email", "type": "email",
             "createable": True, "updateable": True, "nillable": True},
            {"name": "Company", "label": "Company", "type": "string",
             "createable": True, "updateable": True, "nillable": False,
             "defaultedOnCreate": False},
            {"name": "Status", "label": "Status", "type": "picklist",
             "createable": True, "updateable": True, "nillable": True,
             "picklistValues": [{"value": "Open"}, {"value": "Closed"},
                                {"value": None, "active": False}]},
            {"name": "AccountId", "label": "Account ID", "type": "reference",
             "createable": True, "updateable": True, "nillable": True,
             "referenceTo": ["Account"]},
        ],
    }
    patcher, fake = _patch_client([
        *_UPSERT_TOKEN,
        (_json_response(200, describe_body), None),
    ])
    try:
        result = await connector.op_execute("describe", {
            "object_name": "Lead",
        }, {"credentials": CREDS})
    finally:
        patcher.stop()

    out = result["output"]
    assert out["name"] == "Lead"
    fields = {f["name"]: f for f in out["fields"]}
    assert fields["Company"]["required"] is True  # createable + not nillable
    assert fields["Email"]["required"] is False   # nillable
    assert fields["Status"]["picklist_values"] == ["Open", "Closed"]  # None dropped
    assert fields["AccountId"]["reference_to"] == ["Account"]
    assert fields["Id"]["createable"] is False


async def test_query_respects_max_pages_param(connector: SalesforceConnector) -> None:
    page_one = {
        "done": False, "totalSize": 4,
        "records": [{"Id": "1"}],
        "nextRecordsUrl": "/services/data/v63.0/query/01g",
    }
    page_two = {"done": True, "totalSize": 4, "records": [{"Id": "2"}]}
    patcher, fake = _patch_client([
        *_UPSERT_TOKEN,
        (_json_response(200, page_one), None),
        (_json_response(200, page_two), None),
    ])
    try:
        result = await connector.op_execute("query", {
            "soql": "SELECT Id FROM Account",
            "max_pages": 5,
        }, {"credentials": CREDS})
    finally:
        patcher.stop()
    out = result["output"]
    assert out["done"] is True
    assert len(out["records"]) == 2
    assert fake.calls[2][1].endswith("/query/01g")


# ---------------------------------------------------------------------------
# Phase 9: engine honors Retry-After on 429
# ---------------------------------------------------------------------------

async def test_engine_waits_retry_after_before_second_attempt() -> None:
    """A 429 with Retry-After must gate the retry delay."""
    import time as _time

    patcher, fake = _patch_client([
        *_UPSERT_TOKEN,
        (httpx.Response(429, json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "slow"}],
                        headers={"Retry-After": "1"},  # engine should wait ~1s
                        request=httpx.Request("GET", "http://fake")), None),
        (httpx.Response(429, json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "still slow"}],
                        headers={"Retry-After": "1"},
                        request=httpx.Request("GET", "http://fake")), None),
        (httpx.Response(429, json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "give up"}],
                        headers={"Retry-After": "1"},
                        request=httpx.Request("GET", "http://fake")), None),
    ])
    started = _time.monotonic()
    try:
        wf = make_workflow(
            [WorkflowNode(id="sf", type="salesforce", parameters={
                "operation": "get",
                "object_name": "Account",
                "record_id": "001000000000001",
            }, settings={"retry_max_attempts": 2, "retry_backoff_seconds": 0},
               credentials={"salesforce": "cred_1"})],
            wf_id="wf_429",
        )
        result = await execute_workflow(
            wf, [{}],
            credential_resolver=lambda refs: {"salesforce": CREDS["salesforce"]},
        )
    finally:
        patcher.stop()
    elapsed = _time.monotonic() - started
    assert result.status == "failed"
    retries = [e for e in result.events if e.get("event") == "node.retry"]
    assert len(retries) == 2  # 3 scripted 429s => initial + 2 retries
    assert all(r["retry_after_s"] == 1.0 for r in retries)
    # The engine waited the instructed seconds even though backoff was 0.
    assert elapsed >= 1.95

