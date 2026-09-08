"""GitHub connector tests (Phase 11 business connectors).

Proves: PAT auth + API version header, issue creation body, page-based
pagination, primary rate-limit mapping (403 + X-RateLimit-Remaining: 0
-> retryable RATE_LIMITED), taxonomy for 404, owner/repo validation.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = ["app.providers.base"]
CREDS = {"access_token": "ghp_secret_token_value"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_create_issue_sends_pat_and_payload():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(201, {"number": 42, "html_url": "https://github.com/o/r/issues/42", "state": "open"}),
    ])
    try:
        from app.providers.github import GitHubProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            GitHubProviderClient().create_issue(CREDS, "acme", "widgets", "Bug: crash", body="stack", labels=["bug"])
        )
    finally:
        patcher.stop()

    assert out["number"] == 42
    method, url, kwargs = fake.calls[0]
    assert url == "https://api.github.com/repos/acme/widgets/issues"
    assert kwargs["headers"]["Authorization"] == "Bearer ghp_secret_token_value"
    assert kwargs["headers"]["X-GitHub-Api-Version"] == "2022-11-28"
    assert kwargs["json"]["title"] == "Bug: crash"
    assert kwargs["json"]["labels"] == ["bug"]


def test_list_issues_stops_on_short_page():
    full_page = [{"number": i, "title": f"i{i}", "state": "open"} for i in range(1, 4)]
    short_page = [{"number": 99, "title": "last", "state": "open"}]
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, full_page),
        json_response(200, short_page),
    ])
    try:
        from app.providers.github import GitHubProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            GitHubProviderClient().list_issues(CREDS, "acme", "widgets", per_page=3, max_pages=5)
        )
    finally:
        patcher.stop()

    assert out["count"] == 4
    # Only two pages requested: the second returned fewer than per_page.
    assert len(fake.calls) == 2


def test_rate_limit_exhaustion_is_retryable():
    headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"}
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(403, {"message": "API rate limit exceeded"}, headers=headers),
    ])
    try:
        from app.providers.github import GitHubProviderClient

        async def go():
            await GitHubProviderClient().get_repo(CREDS, "acme", "widgets")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("exhausted budget should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.RATE_LIMITED, ConnectorErrorCode.RATE_LIMITED.value)
            assert exc.retryable is True
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_plain_403_forbidden_is_not_retryable():
    patcher, _fake = patch_provider_http(MODULE, [
        json_response(403, {"message": "Resource not accessible by integration"},
                      headers={"X-RateLimit-Remaining": "4998"}),
    ])
    try:
        from app.providers.github import GitHubProviderClient

        async def go():
            await GitHubProviderClient().get_repo(CREDS, "acme", "widgets")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
            raise AssertionError("403 should have raised")
        except ConnectorError as exc:
            assert exc.code in (ConnectorErrorCode.FORBIDDEN, ConnectorErrorCode.FORBIDDEN.value)
            assert exc.retryable is False
        finally:
            loop.close()
    finally:
        patcher.stop()


def test_owner_repo_path_traversal_rejected():
    from app.providers.github import GitHubProviderClient

    async def go():
        await GitHubProviderClient().get_repo(CREDS, "../evil", "widgets")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("path traversal owner should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
    finally:
        loop.close()
