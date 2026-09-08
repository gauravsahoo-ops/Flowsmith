"""Phase 14 — HTTP mock interception (node-level contract).

Guarantees under test:
1. A matched rule answers locally; the real provider is never contacted.
2. While mocks are active, an UNMATCHED outbound call raises
   MockUnmatchedError (strict mode) -> production can never be mutated.
3. With no mocks installed, intercept() returns None (normal traffic).
4. ContextVar reset restores normal behaviour.
"""

from __future__ import annotations

import pytest

from app.security import http_mocks


def _install(rules):
    return http_mocks.install(http_mocks.compile_rules(rules))


@pytest.fixture(autouse=True)
def _no_mocks_after():
    yield
    http_mocks.reset(http_mocks.install(None))


def test_no_mocks_installed_returns_none():
    assert http_mocks.active_rules() is None
    assert http_mocks.intercept("GET", "https://api.example.com/v1/users") is None


def test_matched_rule_answers_locally_with_status_and_body():
    token = _install([
        {"url_pattern": "api.example.com/v1/users", "method": "GET",
         "status": 201, "body": {"ok": True}, "headers": {"X-Test": "1"}},
    ])
    try:
        mocked = http_mocks.intercept("GET", "https://api.example.com/v1/users?page=2")
        assert mocked is not None
        assert mocked["status"] == 201
        assert mocked["json_body"] == {"ok": True}
        assert mocked["headers"] == {"X-Test": "1"}
    finally:
        http_mocks.reset(token)
        assert http_mocks.active_rules() is None


def test_method_mismatch_is_strict_miss_even_when_url_matches():
    _install([{"url_pattern": "api.example.com/v1/users", "method": "GET", "body": {}}])
    with pytest.raises(http_mocks.MockUnmatchedError):
        http_mocks.intercept("DELETE", "https://api.example.com/v1/users/42")


def test_unmatched_call_is_blocked_while_mocking():
    _install([{"url_pattern": "other.host/api", "method": "*"}])
    with pytest.raises(http_mocks.MockUnmatchedError) as excinfo:
        http_mocks.intercept("POST", "https://api.example.com/v1/orders")
    assert "no mock matched" in str(excinfo.value)


def test_wildcard_method_matches_any_verb_and_scheme_agnostic_host_pattern():
    _install([{"url_pattern": "api.example.com/v1/ping"}])  # no method -> any
    for verb in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        assert http_mocks.intercept(verb, "https://api.example.com/v1/ping") is not None


def test_empty_rules_block_everything():
    # A test with zero mock rules is maximally safe: nothing leaves the box.
    http_mocks.install(http_mocks.compile_rules([]))
    with pytest.raises(http_mocks.MockUnmatchedError):
        http_mocks.intercept("GET", "https://anything.internal/x")


def test_connector_error_from_is_non_retryable_bad_request():
    exc = http_mocks.MockUnmatchedError("POST", "https://api.example.com/x")
    err = http_mocks.connector_error_from(exc)
    assert getattr(err, "retryable", True) is False
    assert "no mock matched" in str(err)
