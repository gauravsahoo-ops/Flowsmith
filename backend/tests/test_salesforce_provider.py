"""Salesforce provider client tests (Phase 7).

The provider client is tested with a mocked SafeHTTPClient: token flow,
base URL / API version resolution, request construction, response
parsing, Salesforce error translation, and query pagination.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.connectors import ConnectorErrorCode
from app.providers.salesforce import (
    DEFAULT_API_VERSION,
    SalesforceProviderClient,
)


class FakeHTTPClient:
    """Replaces SafeHTTPClient: scripted responses, recorded calls."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        pass

    async def request(self, method, url, **kwargs) -> httpx.Response:
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _json_response(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "http://fake"))


def _patch_client(responses: list[httpx.Response]):
    fake = FakeHTTPClient(responses)
    cm = MagicMock()
    cm.__aenter__.return_value = fake
    cm.__aexit__ = AsyncMock(return_value=False)
    patcher = patch("app.providers.salesforce.get_safe_http_client", return_value=cm)
    patcher.start()
    return patcher, fake


CREDS = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid",
    "client_secret": "csecret",
    "username": "user@example.com",
    "password": "pass+token",
    "api_version": "v63.0",
}

TOKEN_BODY = {"access_token": "tok123", "instance_url": "https://myorg.salesforce.com"}


@pytest.fixture
def client() -> SalesforceProviderClient:
    return SalesforceProviderClient()


async def test_token_fetch_and_caching(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        await client.query(CREDS, "SELECT Id FROM Account")
        await client.query(CREDS, "SELECT Id FROM Contact")
    finally:
        patcher.stop()

    token_calls = [c for c in fake.calls if c[1].endswith("/services/oauth2/token")]
    assert len(token_calls) == 1  # cached after first fetch
    method, url, kwargs = token_calls[0]
    assert method == "POST"
    assert url == "https://login.salesforce.com/services/oauth2/token"
    assert kwargs["data"] == (
        "grant_type=password&client_id=cid&client_secret=csecret"
        "&username=user%40example.com&password=pass%2Btoken"
    )
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert fake.calls[1][2]["headers"]["Authorization"] == "Bearer tok123"


async def test_token_reused_between_credentials_changes(client: SalesforceProviderClient) -> None:
    """A different username means a different token (cache key)."""
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        other = dict(CREDS, username="other@example.com")
        await client.query(CREDS, "SELECT Id FROM Account")
        await client.query(other, "SELECT Id FROM Account")
    finally:
        patcher.stop()

    token_calls = [c for c in fake.calls if c[1].endswith("/services/oauth2/token")]
    assert len(token_calls) == 2


async def test_sandbox_login_url_used_for_auth(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, {**TOKEN_BODY, "instance_url": "https://myorg--sandbox.sandbox.my.salesforce.com"}),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        creds = dict(CREDS, instance_url="https://test.salesforce.com")
        await client.query(creds, "SELECT Id FROM Account")
    finally:
        patcher.stop()

    assert fake.calls[0][1] == "https://test.salesforce.com/services/oauth2/token"
    # Data requests go to the org instance returned by the token endpoint.
    assert fake.calls[1][1] == "https://myorg--sandbox.sandbox.my.salesforce.com/services/data/v63.0/query"


async def test_request_construction_api_version_and_params(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "001", "Name": "Acme"}]}),
    ])
    try:
        await client.query(CREDS, "SELECT Id, Name FROM Account LIMIT 1", timeout=42.0)
    finally:
        patcher.stop()

    method, url, kwargs = fake.calls[1]
    assert method == "GET"
    assert url == "https://myorg.salesforce.com/services/data/v63.0/query"
    assert kwargs["params"] == {"q": "SELECT Id, Name FROM Account LIMIT 1"}
    assert kwargs["timeout"] == 42.0
    assert kwargs["headers"]["Authorization"] == "Bearer tok123"


async def test_custom_api_version(client: SalesforceProviderClient) -> None:
    provider = SalesforceProviderClient(api_version="v62.0")
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        await provider.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    assert fake.calls[1][1].endswith("/services/data/v62.0/query")


async def test_high_level_operations_build_correct_requests(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"Id": "001", "Name": "Acme"}),
        _json_response(201, {"id": "002", "success": True}),
        _json_response(204, None),
        _json_response(204, None),
    ])
    try:
        record = await client.get_record(CREDS, "Account", "001")
        created = await client.create_record(CREDS, "Account", {"Name": "Acme"})
        await client.update_record(CREDS, "Account", "002", {"Name": "Acme 2"})
        await client.delete_record(CREDS, "Account", "002")
    finally:
        patcher.stop()

    _, get_url, get_kwargs = fake.calls[1]
    assert get_url == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Account/001"
    assert get_kwargs["headers"]["Authorization"] == "Bearer tok123"
    assert record == {"Id": "001", "Name": "Acme"}

    _, create_url, create_kwargs = fake.calls[2]
    assert create_url == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Account"
    assert create_kwargs["json"] == {"Name": "Acme"}
    assert created == {"id": "002", "success": True}

    _, update_url, update_kwargs = fake.calls[3]
    assert update_url == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Account/002"
    assert update_kwargs["json"] == {"Name": "Acme 2"}

    _, delete_url, _delete_kwargs = fake.calls[4]
    assert delete_url == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Account/002"


async def test_query_pagination_follows_next_records_url(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {
            "totalSize": 3, "done": False,
            "records": [{"Id": "001"}, {"Id": "002"}],
            "nextRecordsUrl": "/services/data/v63.0/query/01gAAA",
        }),
        _json_response(200, {
            "totalSize": 3, "done": True,
            "records": [{"Id": "003"}],
        }),
    ])
    try:
        body = await client.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()

    assert len(fake.calls) == 3  # token + page 1 + page 2
    assert [r["Id"] for r in body["records"]] == ["001", "002", "003"]
    assert body["totalSize"] == 3
    assert body["done"] is True
    assert body["nextRecordsUrl"] is None
    # The next page URL is used verbatim (carries its own API version).
    assert fake.calls[2][1] == "https://myorg.salesforce.com/services/data/v63.0/query/01gAAA"


async def test_pagination_stops_at_page_cap(client: SalesforceProviderClient) -> None:
    pages = [
        _json_response(200, {"totalSize": 99, "done": False, "records": [{"Id": str(i)}],
                             "nextRecordsUrl": f"/services/data/v63.0/query/page{i}"})
        for i in range(3)
    ]
    patcher, fake = _patch_client([_json_response(200, TOKEN_BODY), *pages])
    try:
        body = await client.query(CREDS, "SELECT Id FROM Account", max_pages=2)
    finally:
        patcher.stop()

    assert len([c for c in fake.calls if "query" in c[1]]) == 2  # 1 + 1 page
    assert body["done"] is False
    assert body["nextRecordsUrl"] is not None


async def test_error_translation(client: SalesforceProviderClient) -> None:
    cases = [
        (httpx.Response(404, json=[{"message": "Record not found"}], request=httpx.Request("GET", "http://fake")), ConnectorErrorCode.NOT_FOUND, False),
        (httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake")), ConnectorErrorCode.RATE_LIMITED, True),
        (httpx.Response(500, json=[{"message": "Server error"}], request=httpx.Request("GET", "http://fake")), ConnectorErrorCode.UNAVAILABLE, True),
        (httpx.Response(403, json=[{"message": "Forbidden"}], request=httpx.Request("GET", "http://fake")), ConnectorErrorCode.FORBIDDEN, False),
    ]
    for status_response, expected_code, expected_retryable in cases:
        provider = SalesforceProviderClient()
        patcher, _fake = _patch_client([_json_response(200, TOKEN_BODY), status_response])
        try:
            with pytest.raises(Exception) as excinfo:
                await provider.query(CREDS, "SELECT Id FROM Account")
        finally:
            patcher.stop()
        assert getattr(excinfo.value, "code", None) == expected_code.value
        assert getattr(excinfo.value, "retryable", None) is expected_retryable


async def test_error_translation_uses_salesforce_message(client: SalesforceProviderClient) -> None:
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(400, json=[{"message": "INVALID_FIELD: Namey"}], request=httpx.Request("GET", "http://fake")),
    ])
    try:
        with pytest.raises(Exception) as excinfo:
            await client.query(CREDS, "SELECT Namey FROM Account")
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value
    assert "INVALID_FIELD: Namey" in str(excinfo.value)


async def test_auth_errors_are_typed(client: SalesforceProviderClient) -> None:
    cases = [
        (httpx.Response(401, json=[{"message": "invalid_grant"}], request=httpx.Request("GET", "http://fake")), ConnectorErrorCode.AUTH_FAILED, False),
        (httpx.Response(400, json=[{"message": "bad request"}], request=httpx.Request("GET", "http://fake")), ConnectorErrorCode.AUTH_FAILED, False),
        (httpx.Response(502, json={}, request=httpx.Request("GET", "http://fake")), ConnectorErrorCode.BAD_REQUEST, False),
    ]
    for status_response, expected_code, expected_retryable in cases:
        provider = SalesforceProviderClient()
        patcher, _fake = _patch_client([status_response])
        try:
            with pytest.raises(Exception) as excinfo:
                await provider.query(CREDS, "SELECT Id FROM Account")
        finally:
            patcher.stop()
        assert getattr(excinfo.value, "code", None) == expected_code.value
        assert getattr(excinfo.value, "retryable", None) is expected_retryable


async def test_auth_error_includes_salesforce_description(client: SalesforceProviderClient) -> None:
    """Regression (Phase 13): the token endpoint's error_description must
    surface in the connector error so real failures are diagnosable."""
    token_error = httpx.Response(
        400,
        json={"error": "invalid_grant", "error_description": "Invalid username, password, security token; user may not have access."},
        request=httpx.Request("GET", "http://fake"),
    )
    patcher, _fake = _patch_client([token_error])
    try:
        with pytest.raises(Exception) as excinfo:
            await client.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.AUTH_FAILED.value
    assert "Invalid username, password, security token" in str(excinfo.value)
    assert "HTTP 400" in str(excinfo.value)


async def test_malformed_token_response_is_auth_failed(client: SalesforceProviderClient) -> None:
    patcher, _fake = _patch_client([
        httpx.Response(200, json={"no_access_token": True}, request=httpx.Request("GET", "http://fake")),
    ])
    try:
        with pytest.raises(Exception) as excinfo:
            await client.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.AUTH_FAILED.value


async def test_non_json_data_response_is_bad_request(client: SalesforceProviderClient) -> None:
    raw = httpx.Response(200, text="<html>oops</html>", request=httpx.Request("GET", "http://fake"))
    patcher, _fake = _patch_client([_json_response(200, TOKEN_BODY), raw])
    try:
        with pytest.raises(Exception) as excinfo:
            await client.get_record(CREDS, "Account", "001")
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value


async def test_timeout_and_network_errors_are_typed(client: SalesforceProviderClient) -> None:
    patcher = patch("app.providers.salesforce.get_safe_http_client", side_effect=httpx.ConnectTimeout("boom"))
    patcher.start()
    try:
        with pytest.raises(Exception) as excinfo:
            await client.authenticate(CREDS)
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.TIMEOUT.value
    assert getattr(excinfo.value, "retryable", None) is True

    patcher = patch("app.providers.salesforce.get_safe_http_client", side_effect=httpx.NetworkError("boom"))
    patcher.start()
    try:
        with pytest.raises(Exception) as excinfo:
            await client.authenticate(CREDS)
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.UNAVAILABLE.value
    assert getattr(excinfo.value, "retryable", None) is True


async def test_reset_drops_token_and_instance_url(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        await client.query(CREDS, "SELECT Id FROM Account")
        client.reset()
        assert client.has_token is False
        await client.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    token_calls = [c for c in fake.calls if c[1].endswith("/services/oauth2/token")]
    assert len(token_calls) == 2


async def test_concurrent_token_fetch_is_single_flight(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        await asyncio.gather(
            client.query(CREDS, "SELECT Id FROM Account"),
            client.query(CREDS, "SELECT Id FROM Contact"),
        )
    finally:
        patcher.stop()
    token_calls = [c for c in fake.calls if c[1].endswith("/services/oauth2/token")]
    assert len(token_calls) == 1


async def test_custom_api_version_property(client: SalesforceProviderClient) -> None:
    assert client.api_version == DEFAULT_API_VERSION
    assert SalesforceProviderClient(api_version="v59.0").api_version == "v59.0"


# ----------------------------------------------------------------------
# Search/Get Record (Phase 8)
# ----------------------------------------------------------------------


async def test_search_records_found(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qabc"}]}),
        _json_response(200, {"Id": "00Qabc", "Name": "Jane", "Email": "jane@example.com"}),
    ])
    try:
        result = await client.search_records(CREDS, "Lead", "Email", "jane@example.com")
    finally:
        patcher.stop()

    assert result == {"found": True, "record": {"Id": "00Qabc", "Name": "Jane", "Email": "jane@example.com"}}
    method, url, kwargs = fake.calls[1]
    assert url == "https://myorg.salesforce.com/services/data/v63.0/query"
    assert kwargs["params"]["q"] == "SELECT Id FROM Lead WHERE Email = 'jane@example.com' LIMIT 1"
    assert fake.calls[2][1] == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Lead/00Qabc"


async def test_search_records_escapes_soql_value(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        result = await client.search_records(CREDS, "Lead", "Email", "o'brien\\x")
    finally:
        patcher.stop()

    assert result == {"found": False, "record": None}
    _method, _url, kwargs = fake.calls[1]
    assert kwargs["params"]["q"] == "SELECT Id FROM Lead WHERE Email = 'o\\'brien\\\\x' LIMIT 1"


async def test_search_records_not_found_skips_record_fetch(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        result = await client.search_records(CREDS, "Lead", "Email", "nobody@example.com")
    finally:
        patcher.stop()

    assert result == {"found": False, "record": None}
    assert len(fake.calls) == 2  # token + search, no record fetch


# ----------------------------------------------------------------------
# Create Record (Phase 9)
# ----------------------------------------------------------------------


async def test_create_record_success(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(201, {"id": "00Qnew123", "success": True}),
    ])
    try:
        created = await client.create_record(
            CREDS, "Lead",
            {"FirstName": "Automation", "LastName": "Test", "Company": "Test Company", "Email": "test@example.com"},
        )
    finally:
        patcher.stop()

    assert created == {"id": "00Qnew123", "success": True}
    _method, url, kwargs = fake.calls[1]
    assert url == "https://myorg.salesforce.com/services/data/v63.0/sobjects/Lead"
    assert kwargs["json"] == {"FirstName": "Automation", "LastName": "Test", "Company": "Test Company", "Email": "test@example.com"}
    assert kwargs["headers"]["Authorization"] == "Bearer tok123"


async def test_create_record_duplicate_alert_300_reports_success(client: SalesforceProviderClient) -> None:
    """HTTP 300 from a duplicate rule in alert mode: the record IS created,
    so the provider must return success with a duplicate flag and the
    recovered id instead of raising (a duplicate alert must not fail the
    workflow)."""
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(300, json=[{
            "message": "Use one of these records?",
            "errorCode": "DUPLICATES_DETECTED",
            "duplicateResult": {
                "matchedRecords": [
                    {"record": {"Id": "00Qdupe111", "attributes": {}}},
                ],
                "matchResults": [],
            },
        }], request=httpx.Request("GET", "http://fake")),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qnew123"}]}),
    ])
    try:
        created = await client.create_record(
            CREDS, "Lead",
            {"FirstName": "Automation", "LastName": "Test", "Company": "Test Company", "Email": "test@example.com"},
        )
    finally:
        patcher.stop()

    assert created == {
        "id": "00Qnew123",
        "success": True,
        "duplicate_alert": True,
        "matched_records": ["00Qdupe111"],
    }


async def test_create_record_duplicate_alert_300_without_body(client: SalesforceProviderClient) -> None:
    """A 300 whose body carries no duplicateResult and whose recovery query
    finds nothing still reports success with id None."""
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(300, json=[{"message": "Use one of these records?", "errorCode": "DUPLICATES_DETECTED"}], request=httpx.Request("GET", "http://fake")),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        created = await client.create_record(CREDS, "Lead", {"LastName": "Test", "Email": "test@example.com"})
    finally:
        patcher.stop()

    assert created == {"id": None, "success": True, "duplicate_alert": True}


async def test_create_record_duplicate_alert_400_recovered_by_query(client: SalesforceProviderClient) -> None:
    """Some orgs return 400 DUPLICATES_DETECTED for an alert-mode duplicate
    rule; the record IS created, so a follow-up query recovers its id and
    the workflow succeeds."""
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(400, json=[{"message": "Use one of these records?", "errorCode": "DUPLICATES_DETECTED"}], request=httpx.Request("GET", "http://fake")),
        _json_response(200, {"totalSize": 1, "done": True, "records": [{"Id": "00Qrecovered123"}]}),
    ])
    try:
        created = await client.create_record(
            CREDS, "Lead",
            {"FirstName": "Automation", "LastName": "Test", "Company": "Test Company", "Email": "test@example.com"},
        )
    finally:
        patcher.stop()

    assert created == {"id": "00Qrecovered123", "success": True, "duplicate_alert": True}


async def test_create_record_duplicate_block_400_still_raises(client: SalesforceProviderClient) -> None:
    """A true block-mode duplicate rejection (record NOT created) must still
    fail: the follow-up query finds nothing and the error is raised."""
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(400, json=[{"message": "Duplicate value found", "errorCode": "DUPLICATES_DETECTED"}], request=httpx.Request("GET", "http://fake")),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        with pytest.raises(Exception) as excinfo:
            await client.create_record(CREDS, "Lead", {"Email": "test@example.com"})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value


async def test_create_record_api_error_translated(client: SalesforceProviderClient) -> None:
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(400, json=[{"message": "INVALID_FIELD_FOR_INSERT_UPDATE: Email"}], request=httpx.Request("GET", "http://fake")),
    ])
    try:
        with pytest.raises(Exception) as excinfo:
            await client.create_record(CREDS, "Lead", {"Email": "not-an-email"})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.BAD_REQUEST.value
    assert "INVALID_FIELD_FOR_INSERT_UPDATE" in str(excinfo.value)


async def test_create_record_rate_limit_stays_retryable_at_provider(client: SalesforceProviderClient) -> None:
    """The provider reports retryable 429s; the connector downgrades them
    for create (the engine then never auto-retries a create)."""
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(429, json=[{"message": "API_REQUESTS_EXCEEDED"}], request=httpx.Request("GET", "http://fake")),
    ])
    try:
        with pytest.raises(Exception) as excinfo:
            await client.create_record(CREDS, "Lead", {"LastName": "Test"})
    finally:
        patcher.stop()
    assert getattr(excinfo.value, "code", None) == ConnectorErrorCode.RATE_LIMITED.value
    assert getattr(excinfo.value, "retryable", None) is True


# ----------------------------------------------------------------------
# Refresh-token grant (Phase 20)
# ----------------------------------------------------------------------

REFRESH_CREDS = {
    "instance_url": "https://login.salesforce.com",
    "client_id": "cid",
    "client_secret": "csecret",
    "username": "",
    "password": "",
    "refresh_token": "00Drefreshtoken1234567890",
    "api_version": "v63.0",
}


async def test_refresh_token_grant_builds_correct_request(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        await client.query(REFRESH_CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()

    method, url, kwargs = fake.calls[0]
    assert method == "POST"
    assert url == "https://login.salesforce.com/services/oauth2/token"
    assert kwargs["data"] == (
        "grant_type=refresh_token&client_id=cid&client_secret=csecret"
        "&refresh_token=00Drefreshtoken1234567890"
    )
    # Data calls use the instance_url returned by the token endpoint.
    assert fake.calls[1][1] == "https://myorg.salesforce.com/services/data/v63.0/query"
    assert fake.calls[1][2]["headers"]["Authorization"] == "Bearer tok123"


async def test_refresh_token_cached_separately(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"totalSize": 0, "done": True, "records": []}),
    ])
    try:
        other = dict(REFRESH_CREDS, refresh_token="00Dothertoken9999999999")
        await client.query(REFRESH_CREDS, "SELECT Id FROM Account")
        await client.query(other, "SELECT Id FROM Account")
    finally:
        patcher.stop()

    token_calls = [c for c in fake.calls if c[1].endswith("/services/oauth2/token")]
    assert len(token_calls) == 2


async def test_refresh_token_auth_failure_maps_to_auth_failed(client: SalesforceProviderClient) -> None:
    patcher, _fake = _patch_client([
        httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired access/refresh token"},
                       request=httpx.Request("GET", "http://fake")),
    ])
    try:
        with pytest.raises(Exception) as excinfo:
            await client.query(REFRESH_CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    err = excinfo.value
    assert getattr(err, "code", None) == ConnectorErrorCode.AUTH_FAILED.value
    assert getattr(err, "retryable", None) is False
    assert "expired access/refresh token" in str(err)


# ---------------------------------------------------------------------------
# Phase 9: upsert by external id
# ---------------------------------------------------------------------------

async def test_upsert_sends_external_id_patch(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(200, {"id": "001xx", "created": False}),
    ])
    try:
        result = await client.upsert_record(
            CREDS, "Account", "Legacy_Id__c", "L-42",
            {"Name": "Acme", "Legacy_Id__c": "L-42"},
        )
    finally:
        patcher.stop()

    assert result == {"id": "001xx", "created": False}
    method, url, kwargs = fake.calls[1]
    assert method == "PATCH"
    assert url == (
        "https://myorg.salesforce.com/services/data/v63.0"
        "/sobjects/Account/Legacy_Id__c/L-42"
    )
    assert kwargs["json"]["Name"] == "Acme"


async def test_upsert_created_true_on_insert_path(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        _json_response(201, {"id": "001yy", "created": True}),
    ])
    try:
        result = await client.upsert_record(CREDS, "Lead", "Ext__c", "E1", {"Company": "x"})
    finally:
        patcher.stop()
    assert result["created"] is True


async def test_upsert_not_found_maps_to_typed_error(client: SalesforceProviderClient) -> None:
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "nope"}],
                       request=httpx.Request("GET", "http://fake")),
    ])
    try:
        from app.connectors import ConnectorError
        with pytest.raises(ConnectorError) as excinfo:
            await client.upsert_record(CREDS, "Lead", "Ext__c", "missing", {"a": 1})
    finally:
        patcher.stop()
    assert excinfo.value.code == ConnectorErrorCode.NOT_FOUND.value


# ---------------------------------------------------------------------------
# Phase 9: Retry-After parsing on 429
# ---------------------------------------------------------------------------

def test_parse_retry_after_variants() -> None:
    parse = SalesforceProviderClient.parse_retry_after

    class R:
        def __init__(self, headers):
            self.headers = headers

    assert parse(R({"Retry-After": "5"})) == 5.0
    assert parse(R({"Retry-After": "0"})) == 0.0
    assert parse(R({"Retry-After": " 12 "})) == 12.0
    # HTTP-date form and garbage are not supported -> None
    assert parse(R({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})) is None
    assert parse(R({"Retry-After": "soon"})) is None
    assert parse(R({})) is None


async def test_rate_limit_error_carries_retry_after(client: SalesforceProviderClient) -> None:
    """429 responses surface Retry-After seconds on the ConnectorError so
    the engine can wait exactly as long as instructed."""
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(
            429,
            json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "slow down"}],
            headers={"Retry-After": "7"},
            request=httpx.Request("GET", "http://fake"),
        ),
    ])
    try:
        from app.connectors import ConnectorError
        with pytest.raises(ConnectorError) as excinfo:
            await client.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    err = excinfo.value
    assert err.code == ConnectorErrorCode.RATE_LIMITED.value
    assert err.retryable is True
    assert err.retry_after == 7.0


async def test_429_without_retry_after_keeps_none(client: SalesforceProviderClient) -> None:
    patcher, _fake = _patch_client([
        _json_response(200, TOKEN_BODY),
        httpx.Response(
            429,
            json=[{"errorCode": "REQUEST_LIMIT_EXCEEDED", "message": "slow down"}],
            request=httpx.Request("GET", "http://fake"),
        ),
    ])
    try:
        from app.connectors import ConnectorError
        with pytest.raises(ConnectorError) as excinfo:
            await client.query(CREDS, "SELECT Id FROM Account")
    finally:
        patcher.stop()
    assert excinfo.value.retry_after is None


# ---------------------------------------------------------------------------
# Phase 9: Bulk API 2.0 ingest
# ---------------------------------------------------------------------------

def _bulk_job_responses(state_sequence: list[str], *, failed_rows: str = "", ok_rows: str = "") -> list[httpx.Response]:
    """Token + create job + upload + complete + N polls + results."""
    responses: list[httpx.Response] = [_json_response(200, TOKEN_BODY)]
    responses.append(_json_response(201, {"id": "job-1", "state": "Open"}))
    responses.append(httpx.Response(201, request=httpx.Request("PUT", "http://fake")))  # upload
    responses.append(_json_response(200, {"id": "job-1", "state": "UploadComplete"}))  # complete
    for state in state_sequence:
        responses.append(_json_response(200, {
            "id": "job-1", "state": state,
            "numberRecordsProcessed": 2,
            "numberRecordsFailed": 1 if state == "JobComplete" else 0,
        }))
    if state_sequence[-1] == "JobComplete":
        responses.append(httpx.Response(200, text=failed_rows or "sf__Id,Error\n",
                                        request=httpx.Request("GET", "http://fake")))
        responses.append(httpx.Response(200, text=ok_rows or "sf__Id,sf__Created\n",
                                        request=httpx.Request("GET", "http://fake")))
    return responses


async def test_bulk_insert_full_lifecycle(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client(_bulk_job_responses(
        ["InProgress", "JobComplete"],
        failed_rows='sf__Id,Error\n,"BAD FIELD"\n',
        ok_rows="sf__Id,sf__Created\n001a,true\n",
    ))
    try:
        result = await client.bulk_ingest(
            CREDS, "Lead", "insert",
            [{"LastName": "A"}, {"LastName": "B"}],
            poll_interval=0.0,
        )
    finally:
        patcher.stop()

    assert result["state"] == "JobComplete"
    assert result["records_processed"] == 2
    assert result["records_failed"] == 1
    assert result["failed_records"][0]["Error"] == "BAD FIELD"
    assert result["successful_records"][0]["sf__Id"] == "001a"

    # Request shapes: job create, CSV upload, UploadComplete.
    create_call = fake.calls[1]
    assert create_call[1].endswith("/services/data/v63.0/jobs/ingest")
    assert create_call[2]["json"]["operation"] == "insert"
    assert create_call[2]["json"]["object"] == "Lead"

    upload_call = fake.calls[2]
    assert upload_call[1].endswith("/jobs/ingest/job-1/batches")
    assert upload_call[2]["headers"]["Content-Type"] == "text/csv"
    body = upload_call[2]["data"].decode("utf-8")
    assert body.splitlines()[0] == "LastName"
    assert body.splitlines()[1:] == ["A", "B"]

    complete_call = fake.calls[3]
    assert complete_call[1].endswith("/jobs/ingest/job-1")
    assert complete_call[2]["json"] == {"state": "UploadComplete"}

    poll_urls = [c[1] for c in fake.calls[4:6]]
    assert all(u.endswith("/jobs/ingest/job-1") for u in poll_urls)


async def test_bulk_upsert_includes_external_id_field(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client(_bulk_job_responses(["JobComplete"]))
    try:
        await client.bulk_ingest(
            CREDS, "Account", "upsert",
            [{"Legacy_Id__c": "L1", "Name": "N"}],
            external_id_field="Legacy_Id__c",
            poll_interval=0.0,
        )
    finally:
        patcher.stop()
    job_body = fake.calls[1][2]["json"]
    assert job_body["operation"] == "upsert"
    assert job_body["externalIdField"] == "Legacy_Id__c"


async def test_bulk_delete_sends_id_only_csv(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client(_bulk_job_responses(["JobComplete"]))
    try:
        await client.bulk_ingest(
            CREDS, "Lead", "delete",
            [{"Id": "00Q1"}, {"Id": "00Q2", "junk": "dropped"}],
            poll_interval=0.0,
        )
    finally:
        patcher.stop()
    body = fake.calls[2][2]["data"].decode("utf-8")
    lines = body.splitlines()
    assert lines[0] == "Id"
    assert sorted(lines[1:]) == ["00Q1", "00Q2"]


async def test_bulk_failed_job_surfaces_error_message(client: SalesforceProviderClient) -> None:
    responses = [
        _json_response(200, TOKEN_BODY),
        _json_response(201, {"id": "job-x", "state": "Open"}),
        httpx.Response(201, request=httpx.Request("PUT", "http://fake")),
        _json_response(200, {"id": "job-x", "state": "UploadComplete"}),
        _json_response(200, {"id": "job-x", "state": "JobFailed",
                             "errorMessage": "InvalidBatch"},
                        ),
    ]
    patcher, _fake = _patch_client(responses)
    try:
        result = await client.bulk_ingest(
            CREDS, "Lead", "insert", [{"LastName": "A"}], poll_interval=0.0,
        )
    finally:
        patcher.stop()
    assert result["state"] == "JobFailed"
    assert result["error_message"] == "InvalidBatch"


async def test_bulk_poll_timeout_raises_retryable(client: SalesforceProviderClient) -> None:
    responses: list[httpx.Response] = [_json_response(200, TOKEN_BODY)]
    responses.append(_json_response(201, {"id": "job-slow", "state": "Open"}))
    responses.append(httpx.Response(201, request=httpx.Request("PUT", "http://fake")))
    responses.append(_json_response(200, {"id": "job-slow", "state": "UploadComplete"}))
    for _ in range(3):
        responses.append(_json_response(200, {"id": "job-slow", "state": "InProgress"}))
    patcher, _fake = _patch_client(responses)
    try:
        from app.connectors import ConnectorError
        with pytest.raises(ConnectorError) as excinfo:
            await client.bulk_ingest(
                CREDS, "Lead", "insert", [{"LastName": "A"}],
                poll_interval=0.0, max_polls=3,
            )
    finally:
        patcher.stop()
    assert excinfo.value.code == ConnectorErrorCode.TIMEOUT.value
    assert excinfo.value.retryable is True


async def test_bulk_rejects_unknown_operation_and_empty_records(client: SalesforceProviderClient) -> None:
    patcher, fake = _patch_client([])
    try:
        from app.connectors import ConnectorError
        with pytest.raises(ConnectorError):
            await client.bulk_ingest(CREDS, "Lead", "frobnicate", [{"a": 1}])
        with pytest.raises(ConnectorError):
            await client.bulk_ingest(CREDS, "Lead", "insert", [])
        with pytest.raises(ConnectorError):
            await client.bulk_ingest(CREDS, "Lead", "upsert", [{"a": 1}])  # no external id field
    finally:
        patcher.stop()
    assert fake.calls == []  # rejected before any HTTP call


# ---------------------------------------------------------------------------
# Phase 9: Bulk CSV builder
# ---------------------------------------------------------------------------

def test_build_bulk_csv_union_columns_and_quoting() -> None:
    from app.providers.salesforce import build_bulk_csv

    csv_text = build_bulk_csv([
        {"LastName": "A", "Company": "C"},
        {"LastName": "B", "Company": "has,comma"},
        {"LastName": None, "Company": 'quo"te', "Extra": True},
    ])
    lines = csv_text.splitlines()
    assert lines[0] == "LastName,Company,Extra"
    assert '"has,comma"' in lines[2]
    assert '"quo""te"' in lines[3]
    assert lines[3].endswith(",true")


def test_build_bulk_csv_bools_and_none() -> None:
    from app.providers.salesforce import build_bulk_csv

    csv_text = build_bulk_csv([{"Active": False, "Note": None}])
    assert csv_text == "Active,Note\nfalse,\n"