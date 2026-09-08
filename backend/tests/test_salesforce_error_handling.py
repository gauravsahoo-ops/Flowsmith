"""Phase 15: Salesforce error handling.

Every Salesforce failure mode is normalized into the ConnectorError
architecture: a typed code, an explicit retryable flag, and a safe
message. Tests cover the nine failure scenarios (invalid credentials,
expired credentials, invalid object, invalid record, invalid field,
Salesforce API error, rate limit, timeout, network failure), the full
CONNECTOR_* category set, engine retry semantics, and that secrets
(tokens, passwords, Authorization headers) never reach error surfaces.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.connectors import ConnectorErrorCode, get_registry
from app.connectors.salesforce_connector import SalesforceConnector
from app.engine.executor import execute_workflow
from app.providers.salesforce import SalesforceProviderClient
from app.schemas.workflow import WorkflowNode
from tests.conftest import conn, make_node, make_workflow

SF_ID_15 = "00Qabcdefgh1234"

CREDS = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid",
    "client_secret": "csecret",
    "username": "user@example.com",
    "password": "pass+token",
    "api_version": "v63.0",
}

CREDS_CTX = {"salesforce": CREDS}

TOKEN_BODY = {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"}

SECRETS = ["tok123", "csecret", "pass+token", "refresh_token", "Authorization", "Bearer"]

TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"


class FakeHTTPClient:
    """Replaces SafeHTTPClient: scripted responses, recorded calls.

    raise_at: 1-based call indices that raise ReadTimeout instead of
    returning a scripted response (transport-level failures).
    """

    def __init__(self, responses: list[httpx.Response], raise_at: set[int] | None = None) -> None:
        self.responses = list(responses)
        self.raise_at = raise_at or set()
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        if len(self.calls) in self.raise_at:
            raise httpx.ReadTimeout("request timed out")
        return self.responses.pop(0)


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _token_response() -> httpx.Response:
    return _json_response(200, TOKEN_BODY)


def _sf_error(status: int, message: str, error_code: str) -> httpx.Response:
    return httpx.Response(
        status,
        json=[{"errorCode": error_code, "message": message}],
        request=httpx.Request("GET", "http://fake"),
    )


def _patch_client(responses: list[httpx.Response], raise_at: set[int] | None = None):
    fake = FakeHTTPClient(responses, raise_at=raise_at)
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
    from app.connectors import register_builtin_connectors

    register_builtin_connectors()
    yield


async def _expect_connector_error(
    responses: list[httpx.Response], raise_at: set[int] | None = None,
) -> tuple[Any, FakeHTTPClient]:
    provider = SalesforceProviderClient()
    patcher, fake = _patch_client(responses, raise_at=raise_at)
    try:
        with pytest.raises(Exception) as excinfo:
            await provider.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    return excinfo.value, fake


# ----------------------------------------------------------------------
# The nine failure scenarios (Phase 15)
# ----------------------------------------------------------------------


async def test_invalid_credentials_map_to_auth_failed() -> None:
    """Wrong password/security token: the token endpoint rejects the grant."""
    error, _fake = await _expect_connector_error([
        httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "Invalid username, password, security token"},
            request=httpx.Request("GET", "http://fake"),
        ),
    ])
    assert error.code == ConnectorErrorCode.AUTH_FAILED.value
    assert error.retryable is False
    assert "Invalid username, password, security token" in str(error)


async def test_expired_credentials_map_to_auth_failed() -> None:
    """Access token expired: the data API rejects with INVALID_SESSION_ID."""
    error, _fake = await _expect_connector_error([
        _token_response(),
        _sf_error(401, "Session expired or invalid", "INVALID_SESSION_ID"),
    ])
    assert error.code == ConnectorErrorCode.AUTH_FAILED.value
    assert error.retryable is False
    assert "Session expired or invalid" in str(error)


async def test_invalid_object_maps_to_bad_request() -> None:
    """Unknown or mistyped Salesforce object (INVALID_TYPE)."""
    error, _fake = await _expect_connector_error([
        _token_response(),
        _sf_error(400, "The requested resource does not exist", "INVALID_TYPE"),
    ])
    assert error.code == ConnectorErrorCode.BAD_REQUEST.value
    assert error.retryable is False
    assert "requested resource does not exist" in str(error)


async def test_invalid_record_maps_to_bad_request() -> None:
    """Malformed record id (MALFORMED_ID)."""
    error, _fake = await _expect_connector_error([
        _token_response(),
        _sf_error(400, "malformed id 00Q!!bad!!", "MALFORMED_ID"),
    ])
    assert error.code == ConnectorErrorCode.BAD_REQUEST.value
    assert error.retryable is False
    assert "malformed id" in str(error)


async def test_missing_record_maps_to_not_found() -> None:
    """Well-formed but nonexistent record (404)."""
    error, _fake = await _expect_connector_error([
        _token_response(),
        _sf_error(404, "The requested resource does not exist", "NOT_FOUND"),
    ])
    assert error.code == ConnectorErrorCode.NOT_FOUND.value
    assert error.retryable is False


async def test_invalid_field_maps_to_bad_request() -> None:
    """Field referenced by query/update does not exist (INVALID_FIELD)."""
    error, _fake = await _expect_connector_error([
        _token_response(),
        _sf_error(400, "INVALID_FIELD: Companyy", "INVALID_FIELD"),
    ])
    assert error.code == ConnectorErrorCode.BAD_REQUEST.value
    assert error.retryable is False
    assert "INVALID_FIELD: Companyy" in str(error)


async def test_salesforce_api_error_maps_to_unavailable() -> None:
    """Internal provider failure (5xx) is a retryable outage."""
    for status in (500, 502, 503):
        error, _fake = await _expect_connector_error([
            _token_response(),
            _sf_error(status, "Service temporarily unavailable", "GENERAL_EXCEPTION"),
        ])
        assert error.code == ConnectorErrorCode.UNAVAILABLE.value, status
        assert error.retryable is True, status


async def test_rate_limit_maps_to_retryable_rate_limited() -> None:
    """API_REQUEST_LIMIT_EXCEEDED (429) is retryable."""
    error, _fake = await _expect_connector_error([
        _token_response(),
        _sf_error(429, "API_REQUESTS_EXCEEDED", "API_REQUESTS_EXCEEDED"),
    ])
    assert error.code == ConnectorErrorCode.RATE_LIMITED.value
    assert error.retryable is True


async def test_forbidden_maps_to_connector_forbidden() -> None:
    """Authenticated but not authorized for the resource (403)."""
    error, _fake = await _expect_connector_error([
        _token_response(),
        _sf_error(403, "Forbidden: insufficient privileges", "INSUFFICIENT_ACCESS"),
    ])
    assert error.code == ConnectorErrorCode.FORBIDDEN.value
    assert error.retryable is False


async def test_timeout_maps_to_retryable_timeout() -> None:
    """The data API hangs: ReadTimeout is CONNECTOR_TIMEOUT and retryable."""
    error, _fake = await _expect_connector_error(
        [_token_response(), _json_response(200, {"totalSize": 0, "done": True, "records": []})],
        raise_at={2},
    )
    assert error.code == ConnectorErrorCode.TIMEOUT.value
    assert error.retryable is True
    assert "timed out" in str(error)


async def test_network_failure_maps_to_retryable_unavailable() -> None:
    """The org is unreachable: transport errors are retryable outages."""
    patcher = patch("app.providers.salesforce.get_safe_http_client", side_effect=httpx.ConnectError("connection refused"))
    patcher.start()
    try:
        with pytest.raises(Exception) as excinfo:
            provider = SalesforceProviderClient()
            await provider.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    error = excinfo.value
    assert getattr(error, "code", None) == ConnectorErrorCode.UNAVAILABLE.value
    assert getattr(error, "retryable", None) is True
    assert "connection refused" in str(error)


# ----------------------------------------------------------------------
# Category coverage: every CONNECTOR_* category the phase requires
# ----------------------------------------------------------------------


async def test_all_required_categories_covered_with_consistent_retryability() -> None:
    """Each requested category has a scenario and the right retryable flag."""
    cases = [
        (ConnectorErrorCode.AUTH_FAILED, False),
        (ConnectorErrorCode.RATE_LIMITED, True),
        (ConnectorErrorCode.TIMEOUT, True),
        (ConnectorErrorCode.BAD_REQUEST, False),
        (ConnectorErrorCode.NOT_FOUND, False),
        (ConnectorErrorCode.FORBIDDEN, False),
        (ConnectorErrorCode.UNAVAILABLE, True),
    ]
    responses_by_code = {
        ConnectorErrorCode.AUTH_FAILED: _sf_error(401, "bad", "INVALID_SESSION_ID"),
        ConnectorErrorCode.RATE_LIMITED: _sf_error(429, "bad", "API_REQUESTS_EXCEEDED"),
        ConnectorErrorCode.BAD_REQUEST: _sf_error(400, "bad", "INVALID_FIELD"),
        ConnectorErrorCode.NOT_FOUND: _sf_error(404, "bad", "NOT_FOUND"),
        ConnectorErrorCode.FORBIDDEN: _sf_error(403, "bad", "INSUFFICIENT_ACCESS"),
        ConnectorErrorCode.UNAVAILABLE: _sf_error(500, "bad", "GENERAL_EXCEPTION"),
    }
    for code, expected_retryable in cases:
        if code is ConnectorErrorCode.TIMEOUT:
            error, _fake = await _expect_connector_error(
                [_token_response(), _json_response(200, {"totalSize": 0, "done": True, "records": []})],
                raise_at={2},
            )
        else:
            error, _fake = await _expect_connector_error([_token_response(), responses_by_code[code]])
        assert error.code == code.value, code
        assert error.retryable is expected_retryable, code


# ----------------------------------------------------------------------
# Secrets never reach error surfaces (Phase 15)
# ----------------------------------------------------------------------


async def test_errors_never_expose_secrets() -> None:
    """Every failure surface is swept: tokens, secrets, Authorization headers."""
    scenarios = [
        # (label, responses, raise_at)
        ("invalid credentials", [
            httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad grant"},
                           request=httpx.Request("GET", "http://fake")),
        ], None),
        ("expired credentials", [_token_response(), _sf_error(401, "expired", "INVALID_SESSION_ID")], None),
        ("invalid object", [_token_response(), _sf_error(400, "no object", "INVALID_TYPE")], None),
        ("invalid record", [_token_response(), _sf_error(400, "bad id", "MALFORMED_ID")], None),
        ("invalid field", [_token_response(), _sf_error(400, "bad field", "INVALID_FIELD")], None),
        ("api error", [_token_response(), _sf_error(500, "server error", "GENERAL_EXCEPTION")], None),
        ("rate limit", [_token_response(), _sf_error(429, "limited", "API_REQUESTS_EXCEEDED")], None),
        ("forbidden", [_token_response(), _sf_error(403, "nope", "INSUFFICIENT_ACCESS")], None),
        ("not found", [_token_response(), _sf_error(404, "gone", "NOT_FOUND")], None),
        ("timeout", [_token_response(), _json_response(200, {"totalSize": 0, "done": True, "records": []})], {2}),
    ]
    for label, responses, raise_at in scenarios:
        provider = SalesforceProviderClient()
        patcher, fake = _patch_client(responses, raise_at=raise_at)
        try:
            with pytest.raises(Exception) as excinfo:
                await provider.query(CREDS, "SELECT Id FROM Account")
        finally:
            patcher.stop()
        error = excinfo.value
        text = str(error)
        for secret in SECRETS:
            assert secret not in text, f"{label}: '{secret}' leaked into error: {text!r}"
        assert str(getattr(error, "code", "")).startswith("CONNECTOR_"), label
        assert isinstance(getattr(error, "retryable", None), bool), label
        # sanity: the real token/credentials really were in flight, so the sweep is meaningful
        token_calls = [c for c in fake.calls if c[1] == TOKEN_URL]
        data_calls = [c for c in fake.calls if c[1] != TOKEN_URL]
        assert token_calls, label
        if data_calls:
            assert all("Bearer tok123" == c[2]["headers"].get("Authorization") for c in data_calls), label


async def test_connector_level_error_preserves_code_and_hides_secrets() -> None:
    """The connector re-raises the provider code and never leaks secrets."""
    patcher, fake = _patch_client([
        _token_response(),
        _sf_error(401, "Session expired or invalid", "INVALID_SESSION_ID"),
    ])
    connector = SalesforceConnector()
    try:
        with pytest.raises(Exception) as excinfo:
            await connector.op_execute("execute", {
                "operation": "get",
                "object_name": "Lead",
                "record_id": SF_ID_15,
            }, {"credentials": CREDS_CTX})
    finally:
        patcher.stop()
    error = excinfo.value
    assert getattr(error, "code", None) == ConnectorErrorCode.AUTH_FAILED.value
    assert getattr(error, "retryable", None) is False
    for secret in SECRETS:
        assert secret not in str(error)
    auth_headers = [c[2]["headers"].get("Authorization") for c in fake.calls if c[1] != TOKEN_URL]
    assert auth_headers and all("Bearer tok123" == h for h in auth_headers)


async def test_engine_error_result_is_typed_and_secret_free() -> None:
    """Failed runs surface code/retryable/message with no secrets."""
    patcher, fake = _patch_client([
        _token_response(),
        _sf_error(403, "Forbidden: insufficient privileges", "INSUFFICIENT_ACCESS"),
    ])
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             WorkflowNode(
                 id="sf", type="salesforce",
                 parameters={"operation": "get", "object_name": "Lead", "record_id": SF_ID_15},
                 settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0.01},
                 credentials={"salesforce": "cred_1"},
             )],
            [conn("trigger", "sf")],
        )
        result = await execute_workflow(wf, [{}], credential_resolver=lambda refs: CREDS_CTX)
    finally:
        patcher.stop()

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == ConnectorErrorCode.FORBIDDEN.value
    assert result.error.retryable is False
    assert "Forbidden: insufficient privileges" in result.error.message
    for secret in SECRETS:
        assert secret not in result.error.message
        assert secret not in str(result.error.to_dict())


# ----------------------------------------------------------------------
# Engine retry semantics driven by the retryable flag
# ----------------------------------------------------------------------


async def test_engine_does_not_retry_non_retryable_forbidden() -> None:
    """CONNECTOR_FORBIDDEN is not retried: exactly one data attempt."""
    patcher, fake = _patch_client([
        _token_response(),
        _sf_error(403, "Forbidden: insufficient privileges", "INSUFFICIENT_ACCESS"),
    ])
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             WorkflowNode(
                 id="sf", type="salesforce",
                 parameters={"operation": "get", "object_name": "Lead", "record_id": SF_ID_15},
                 settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0.01},
                 credentials={"salesforce": "cred_1"},
             )],
            [conn("trigger", "sf")],
        )
        result = await execute_workflow(wf, [{}], credential_resolver=lambda refs: CREDS_CTX)
    finally:
        patcher.stop()

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == ConnectorErrorCode.FORBIDDEN.value
    data_calls = [c for c in fake.calls if c[1] != TOKEN_URL]
    assert len(data_calls) == 1  # no retry on non-retryable


async def test_engine_retries_retryable_timeout_and_succeeds() -> None:
    """CONNECTOR_TIMEOUT is retried: the second attempt succeeds."""
    patcher, fake = _patch_client([
        _token_response(),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc"}]}),
    ], raise_at={2})
    try:
        wf = make_workflow(
            [make_node("trigger", "manual_trigger"),
             WorkflowNode(
                 id="sf", type="salesforce",
                 parameters={"operation": "query", "soql": "SELECT Id FROM Lead"},
                 settings={"retry_max_attempts": 3, "retry_backoff_seconds": 0.01},
                 credentials={"salesforce": "cred_1"},
             )],
            [conn("trigger", "sf")],
        )
        result = await execute_workflow(wf, [{}], credential_resolver=lambda refs: CREDS_CTX)
    finally:
        patcher.stop()

    assert result.status == "success"
    assert result.results["sf"]["main"][0]["records"][0]["Id"] == "00Qabc"
    data_calls = [c for c in fake.calls if c[1] != TOKEN_URL]
    assert len(data_calls) == 2  # timed-out attempt + retried attempt