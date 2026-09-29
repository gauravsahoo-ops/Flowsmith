"""Live integration tests for Enterprise Connectors (Phase 41).

Tests real API execution for enterprise connectors when FLOWSMITH_LIVE_TESTS=true
and corresponding credentials are supplied in environment variables.

Skips cleanly as LIVE_TEST_UNAVAILABLE when credentials are missing.
"""

from __future__ import annotations

import time
import pytest

from app.connectors.salesforce_connector import SalesforceConnector
from app.connectors.github_connector import GitHubConnector
from app.connectors.slack_connector import SlackConnector
from app.connectors.sendgrid_connector import SendGridConnector
from app.connectors.stripe_connector import StripeConnector
from tests.live_integrations.harness import (
    live_registry,
    require_live_credentials,
)

pytestmark = [pytest.mark.live]


def test_salesforce_live_query() -> None:
    """Live verification of Salesforce SOQL query."""
    creds = require_live_credentials("salesforce", ["SALESFORCE_INSTANCE_URL", "SALESFORCE_ACCESS_TOKEN"])
    conn = SalesforceConnector()
    start_t = time.time()
    try:
        res = conn.op_execute(
            operation="query_records",
            parameters={"query": "SELECT Id, Name FROM Account LIMIT 1"},
            credentials={
                "instance_url": creds["SALESFORCE_INSTANCE_URL"],
                "access_token": creds["SALESFORCE_ACCESS_TOKEN"],
            },
        )
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="salesforce",
            operation="query_records",
            status="LIVE_SUCCESS",
            duration_ms=duration_ms,
            status_code=200,
        )
        assert "records" in res
    except Exception as exc:
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="salesforce",
            operation="query_records",
            status="LIVE_FAILED",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise


def test_github_live_get_user() -> None:
    """Live verification of GitHub user lookup."""
    creds = require_live_credentials("github", ["GITHUB_TOKEN"])
    conn = GitHubConnector()
    start_t = time.time()
    try:
        res = conn.op_execute(
            operation="get_user",
            parameters={"username": "octocat"},
            credentials={"token": creds["GITHUB_TOKEN"]},
        )
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="github",
            operation="get_user",
            status="LIVE_SUCCESS",
            duration_ms=duration_ms,
            status_code=200,
        )
        assert res.get("login") == "octocat"
    except Exception as exc:
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="github",
            operation="get_user",
            status="LIVE_FAILED",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise


def test_slack_live_auth_test() -> None:
    """Live verification of Slack auth test."""
    creds = require_live_credentials("slack", ["SLACK_BOT_TOKEN"])
    conn = SlackConnector()
    start_t = time.time()
    try:
        res = conn.op_execute(
            operation="auth_test",
            parameters={},
            credentials={"bot_token": creds["SLACK_BOT_TOKEN"]},
        )
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="slack",
            operation="auth_test",
            status="LIVE_SUCCESS",
            duration_ms=duration_ms,
            status_code=200,
        )
        assert res.get("ok") is True
    except Exception as exc:
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="slack",
            operation="auth_test",
            status="LIVE_FAILED",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise


def test_sendgrid_live_api_key_check() -> None:
    """Live verification of SendGrid API credentials."""
    creds = require_live_credentials("sendgrid", ["SENDGRID_API_KEY"])
    conn = SendGridConnector()
    start_t = time.time()
    try:
        res = conn.op_execute(
            operation="get_verified_senders",
            parameters={},
            credentials={"api_key": creds["SENDGRID_API_KEY"]},
        )
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="sendgrid",
            operation="get_verified_senders",
            status="LIVE_SUCCESS",
            duration_ms=duration_ms,
            status_code=200,
        )
        assert isinstance(res, (dict, list))
    except Exception as exc:
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="sendgrid",
            operation="get_verified_senders",
            status="LIVE_FAILED",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise


def test_stripe_live_balance() -> None:
    """Live verification of Stripe balance."""
    creds = require_live_credentials("stripe", ["STRIPE_API_KEY"])
    conn = StripeConnector()
    start_t = time.time()
    try:
        res = conn.op_execute(
            operation="get_balance",
            parameters={},
            credentials={"api_key": creds["STRIPE_API_KEY"]},
        )
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="stripe",
            operation="get_balance",
            status="LIVE_SUCCESS",
            duration_ms=duration_ms,
            status_code=200,
        )
        assert "object" in res
    except Exception as exc:
        duration_ms = (time.time() - start_t) * 1000
        live_registry.record(
            connector_key="stripe",
            operation="get_balance",
            status="LIVE_FAILED",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise
