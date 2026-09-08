"""Jira connector tests (Phase 11 business connectors).

Proves: Basic auth header from email+token, https-only site enforcement,
JQL search with startAt pagination, ADF description body on create.
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from app.connectors import ConnectorError, ConnectorErrorCode, get_registry, register_builtin_connectors
from tests.test_api._connector_fakes import json_response, patch_provider_http

MODULE = "app.providers.jira"
CREDS = {"site_url": "https://acme.atlassian.net", "email": "bot@acme.com", "api_token": "jira-token-secret"}


@pytest.fixture(autouse=True)
def _connectors():
    registry = get_registry()
    registry.initialize()
    register_builtin_connectors()


def test_search_uses_basic_auth_and_paginates():
    page1 = {
        "issues": [
            {"key": "PROJ-1", "fields": {"summary": "First", "status": {"name": "Open"}, "issuetype": {"name": "Bug"}}},
            {"key": "PROJ-2", "fields": {"summary": "Second", "status": {"name": "Done"}, "issuetype": {"name": "Task"}}},
        ],
        "total": 3,
    }
    page2 = {
        "issues": [{"key": "PROJ-3", "fields": {"summary": "Third", "status": {"name": "Open"}, "issuetype": {"name": "Task"}}}],
        "total": 3,
    }
    patcher, fake = patch_provider_http(MODULE, [
        json_response(200, page1),
        json_response(200, page2),
    ])
    try:
        from app.providers.jira import JiraProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            JiraProviderClient().search(CREDS, "project = PROJ ORDER BY updated DESC", max_results=2)
        )
    finally:
        patcher.stop()

    assert [i["key"] for i in out["issues"]] == ["PROJ-1", "PROJ-2", "PROJ-3"]
    assert out["total"] == 3

    expected_header = base64.b64encode(b"bot@acme.com:jira-token-secret").decode()
    method, url, kwargs = fake.calls[0]
    assert url.startswith("https://acme.atlassian.net/rest/api/3/search")
    assert kwargs["headers"]["Authorization"] == f"Basic {expected_header}"
    assert kwargs["params"]["startAt"] == 0
    _, _, kwargs2 = fake.calls[1]
    assert kwargs2["params"]["startAt"] == 2


def test_site_must_be_https():
    from app.providers.jira import JiraProviderClient

    async def go():
        await JiraProviderClient().search(
            {**CREDS, "site_url": "http://acme.atlassian.net"}, "ORDER BY updated"
        )

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("http site should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.NOT_CONFIGURED, ConnectorErrorCode.NOT_CONFIGURED.value)
        assert "https" in str(exc)
    finally:
        loop.close()


def test_create_issue_builds_adf_description():
    patcher, fake = patch_provider_http(MODULE, [
        json_response(201, {"id": "10001", "key": "PROJ-9"}),
    ])
    try:
        from app.providers.jira import JiraProviderClient

        out = asyncio.new_event_loop().run_until_complete(
            JiraProviderClient().create_issue(
                CREDS, "PROJ", "Bug", "Crash on save", description="steps to repro",
            )
        )
    finally:
        patcher.stop()

    assert out == {"key": "PROJ-9", "id": "10001", "success": True}
    _, _, kwargs = fake.calls[0]
    body = kwargs["json"]["fields"]
    assert body["project"] == {"key": "PROJ"}
    assert body["issuetype"] == {"name": "Bug"}
    assert body["description"]["type"] == "doc"
    assert body["description"]["content"][0]["content"][0]["text"] == "steps to repro"


def test_bad_issue_key_rejected():
    from app.providers.jira import JiraProviderClient

    async def go():
        await JiraProviderClient().add_comment(CREDS, "not-a-key", "hi")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
        raise AssertionError("bad issue key should have raised")
    except ConnectorError as exc:
        assert exc.code in (ConnectorErrorCode.BAD_REQUEST, ConnectorErrorCode.BAD_REQUEST.value)
        assert "PROJ-123" in str(exc)
    finally:
        loop.close()
