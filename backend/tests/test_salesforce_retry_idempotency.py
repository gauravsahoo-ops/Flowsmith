"""Phase 16: Salesforce retry & idempotency.

Reviews every Salesforce operation against the existing engine retry
system (no redesign):

- Search/Get/Query (reads) and Update/Delete (idempotent writes) are
  retried on transient provider errors (429, timeout, 5xx) with
  exponential backoff.
- Create is non-idempotent: the connector downgrades every provider
  error to non-retryable, so the engine NEVER auto-retries it — an
  ambiguous create failure must not silently duplicate a record.

Verifies retry count, backoff (including the 60s cap), node timeout
semantics (NODE_TIMEOUT is retryable), the failure state after
exhausted attempts (typed error + downstream skipped), and execution
history (trace notes + API execution detail).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.connectors import ConnectorErrorCode, get_registry, register_builtin_connectors
from app.engine.executor import MAX_RETRY_BACKOFF_S, execute_workflow
from app.schemas.workflow import WorkflowNode
from tests.conftest import conn, make_node, make_workflow
from tests.test_api.conftest import auth_headers, register

SF_ID_15 = "00Qabcdefgh1234"
TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"

CREDS_CTX = {
    "salesforce": {
        "instance_url": "https://login.salesforce.com",
        "client_id": "cid",
        "client_secret": "csecret",
        "username": "user@example.com",
        "password": "pass+token",
        "api_version": "v63.0",
    }
}

SF_DATA = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid_123",
    "client_secret": "S3CR3T_CLIENT_SECRET_ZZZ",
    "username": "user@example.com",
    "password": "P4SS_+_TOK3N_ZZZ",
    "api_version": "v63.0",
}

TOKEN_BODY = {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"}

RETRY_SETTINGS = {"retry_max_attempts": 2, "retry_backoff_seconds": 0.01}


class FakeHTTPClient:
    """Scripted SafeHTTPClient: token + data responses, optional raise/sleep."""

    def __init__(
        self,
        responses: list[httpx.Response],
        raise_at: set[int] | None = None,
        sleep_on: dict[int, float] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.raise_at = raise_at or set()
        self.sleep_on = sleep_on or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        if len(self.calls) in self.raise_at:
            raise httpx.ReadTimeout("request timed out")
        delay = self.sleep_on.get(len(self.calls))
        if delay:
            await asyncio.sleep(delay)
        return self.responses.pop(0)

    @property
    def data_calls(self) -> list[Any]:
        return [c for c in self.calls if c[1] != TOKEN_URL]


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _token_response() -> httpx.Response:
    return _json_response(200, TOKEN_BODY)


def _sf_error(status: int, message: str = "API error") -> httpx.Response:
    return httpx.Response(
        status, json=[{"errorCode": "X", "message": message}],
        request=httpx.Request("GET", "http://fake"),
    )


def _patch_client(responses: list[httpx.Response], **kwargs: Any):
    fake = FakeHTTPClient(responses, **kwargs)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.salesforce.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


@pytest.fixture(autouse=True)
def _connectors_registered():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()
    yield


def _salesforce_node(
    node_id: str,
    operation: str,
    extra: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> WorkflowNode:
    base: dict[str, Any] = {"operation": operation, "object_name": "Lead"}
    if operation in ("get", "update", "delete"):
        base["record_id"] = SF_ID_15
    if operation == "update":
        base["record"] = {"Company": "Acme"}
    if operation == "query":
        base = {"operation": "query", "soql": "SELECT Id FROM Lead"}
    if operation == "search":
        base.update({"search_field": "Email", "search_value": "a@b.com"})
    base.update(extra or {})
    return WorkflowNode(
        id=node_id, type="salesforce",
        parameters=base,
        settings=settings or RETRY_SETTINGS,
        credentials={"salesforce": "cred_1"},
    )


def _run(wf: Any, events: list[dict[str, Any]] | None = None):
    return execute_workflow(
        wf, [{}],
        credential_resolver=lambda refs: CREDS_CTX,
        event_sink=events.append if events is not None else None,
    )


def _retry_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e.get("event") == "node.retry"]


# ----------------------------------------------------------------------
# Search / Get: safe retry on transient provider errors (reads)
# ----------------------------------------------------------------------


async def test_search_retried_on_rate_limit_and_succeeds() -> None:
    """Search is a safe read: a 429 is retried once, then succeeds."""
    patcher, fake = _patch_client([
        _token_response(),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qx"}]}),
        _json_response(200, {"Id": "00Qx", "Name": "Jane", "Email": "a@b.com"}),
    ])
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"), _salesforce_node("sf", "search")],
            [conn("trigger", "sf")],
        )
        result = await _run(wf)
    finally:
        patcher.stop()

    assert result.status == "success"
    assert result.results["sf"]["main"][0]["record"]["Email"] == "a@b.com"
    # token + failed search + retried search + record fetch
    assert len(fake.data_calls) == 3
    note = [s for s in result.trace if s["node_id"] == "sf"][0]["note"]
    assert "succeeded after 1 retries" in note


async def test_get_retried_on_timeout_and_succeeds() -> None:
    """Get is a safe read: a timeout is retried, then succeeds."""
    patcher, fake = _patch_client(
        [_token_response(), _json_response(200, {"Id": SF_ID_15, "Name": "Acme"})],
        raise_at={2},
    )
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"), _salesforce_node("sf", "get")],
            [conn("trigger", "sf")],
        )
        result = await _run(wf)
    finally:
        patcher.stop()

    assert result.status == "success"
    assert result.results["sf"]["main"][0]["record"]["Id"] == SF_ID_15
    assert len(fake.data_calls) == 2  # timed-out attempt + retried attempt


# ----------------------------------------------------------------------
# Create: never blindly retried (duplicate protection)
# ----------------------------------------------------------------------


async def test_create_never_retried_despite_retry_settings() -> None:
    """Even with retry_max_attempts=2, a 429 on create runs exactly once."""
    patcher, fake = _patch_client([
        _token_response(),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
    ])
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             _salesforce_node("sf", "create", extra={"record": {"Company": "Acme"}})],
            [conn("trigger", "sf")],
        )
        result = await _run(wf)
    finally:
        patcher.stop()

    assert result.status == "failed"
    assert len(fake.data_calls) == 1  # exactly one create attempt
    assert result.error is not None
    assert result.error.code == ConnectorErrorCode.RATE_LIMITED.value
    assert result.error.retryable is False
    assert result.node_errors["sf"].code == ConnectorErrorCode.RATE_LIMITED.value


async def test_create_timeout_never_retried() -> None:
    """A timeout on create is also not retried: the write is ambiguous."""
    patcher, fake = _patch_client(
        [_token_response(), _json_response(201, {"id": "00Qnew", "success": True})],
        raise_at={2},
    )
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             _salesforce_node("sf", "create", extra={"record": {"Company": "Acme"}})],
            [conn("trigger", "sf")],
        )
        result = await _run(wf)
    finally:
        patcher.stop()

    assert result.status == "failed"
    assert len(fake.data_calls) == 1
    assert result.error is not None
    assert result.error.code == ConnectorErrorCode.TIMEOUT.value
    assert result.error.retryable is False


# ----------------------------------------------------------------------
# Update: safe retry (idempotent re-apply of the same fields)
# ----------------------------------------------------------------------


async def test_update_retries_with_exponential_backoff_until_exhausted() -> None:
    """Update retries on 429 with exponential backoff; after the budget is
    spent the run fails with a typed, retryable error and downstream nodes
    are skipped."""
    patcher, fake = _patch_client([
        _token_response(),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
    ])
    events: list[dict[str, Any]] = []
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             _salesforce_node("sf", "update"),
             make_node("sd", "set_data", {"fields": {"done": True}})],
            [conn("trigger", "sf"), conn("sf", "sd")],
        )
        result = await _run(wf, events)
    finally:
        patcher.stop()

    # retry count: max_attempts = retry_max_attempts(2) + 1 = 3 data calls
    assert len(fake.data_calls) == 3

    # backoff: exponential, starting at the configured base
    retries = _retry_events(events)
    assert [r["attempt"] for r in retries] == [1, 2]
    assert [r["retry_after_s"] for r in retries] == [0.01, 0.02]
    assert all(r["max_attempts"] == 3 for r in retries)
    assert all(r["error"]["code"] == ConnectorErrorCode.RATE_LIMITED.value for r in retries)

    # failure state: typed error, retryable, trace step, downstream skipped
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == ConnectorErrorCode.RATE_LIMITED.value
    assert result.error.retryable is True
    assert result.node_errors["sf"].code == ConnectorErrorCode.RATE_LIMITED.value
    sf_step = [s for s in result.trace if s["node_id"] == "sf"][0]
    assert sf_step["status"] == "error"
    assert "3 attempt(s)" in sf_step["note"]
    sd_step = [s for s in result.trace if s["node_id"] == "sd"][0]
    assert sd_step["status"] == "skipped"
    assert "sd" in result.skipped


async def test_update_backoff_capped_at_maximum() -> None:
    """Exponential backoff never exceeds MAX_RETRY_BACKOFF_S."""
    patcher, fake = _patch_client([
        _token_response(),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
        _sf_error(429, "API_REQUESTS_EXCEEDED"),
    ])
    events: list[dict[str, Any]] = []
    original_cap = MAX_RETRY_BACKOFF_S
    try:
        with patch("app.engine.executor.MAX_RETRY_BACKOFF_S", 0.03):
            wf = make_workflow(
                [make_node("trigger", "manual_trigger"),
                 _salesforce_node(
                     "sf", "update",
                     settings={"retry_max_attempts": 2, "retry_backoff_seconds": 0.05},
                 )],
                [conn("trigger", "sf")],
            )
            result = await _run(wf, events)
    finally:
        patcher.stop()
    assert original_cap == 60.0  # the real cap is unchanged

    assert result.status == "failed"
    # delays would be 0.05 -> 0.1 without the cap; both clamped to 0.03
    assert [r["retry_after_s"] for r in _retry_events(events)] == [0.03, 0.03]


async def test_update_retried_on_timeout_and_succeeds() -> None:
    """An idempotent update survives a timeout via retry."""
    patcher, fake = _patch_client(
        [_token_response(), _json_response(204, {})],
        raise_at={2},
    )
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"), _salesforce_node("sf", "update")],
            [conn("trigger", "sf")],
        )
        result = await _run(wf)
    finally:
        patcher.stop()

    assert result.status == "success"
    assert len(fake.data_calls) == 2


# ----------------------------------------------------------------------
# Node timeout: NODE_TIMEOUT is retryable and retried by the engine
# ----------------------------------------------------------------------


async def test_node_timeout_retried_then_succeeds() -> None:
    """The node-level timeout_seconds produces NODE_TIMEOUT (retryable);
    the engine retries and the second attempt succeeds."""
    patcher, fake = _patch_client(
        [_token_response(), _json_response(200, {"Id": SF_ID_15, "Name": "Acme"})],
        sleep_on={2: 0.2},  # attempt 1 is too slow
    )
    events: list[dict[str, Any]] = []
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             _salesforce_node(
                 "sf", "get",
                 settings={"retry_max_attempts": 1, "retry_backoff_seconds": 0.01, "timeout_seconds": 0.05},
             )],
            [conn("trigger", "sf")],
        )
        result = await _run(wf, events)
    finally:
        patcher.stop()

    assert result.status == "success"
    assert len(fake.data_calls) == 2
    retries = _retry_events(events)
    assert [r["attempt"] for r in retries] == [1]
    note = [s for s in result.trace if s["node_id"] == "sf"][0]["note"]
    assert "succeeded after 1 retries" in note


async def test_node_timeout_exhausted_fails_with_typed_state() -> None:
    """When every attempt exceeds the node timeout, the run fails with
    NODE_TIMEOUT (retryable=True) and the budget is recorded."""
    patcher, fake = _patch_client(
        [_token_response(), _json_response(200, {"Id": SF_ID_15})],
        sleep_on={2: 0.2, 3: 0.2},
    )
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             _salesforce_node(
                 "sf", "get",
                 settings={"retry_max_attempts": 1, "retry_backoff_seconds": 0.01, "timeout_seconds": 0.05},
             )],
            [conn("trigger", "sf")],
        )
        result = await _run(wf)
    finally:
        patcher.stop()

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "NODE_TIMEOUT"
    assert result.error.retryable is True
    sf_step = [s for s in result.trace if s["node_id"] == "sf"][0]
    assert sf_step["status"] == "error"
    assert "2 attempt(s)" in sf_step["note"]
    assert "1 failed retry" in sf_step["note"]

