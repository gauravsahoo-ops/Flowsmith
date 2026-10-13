"""Unit tests for Batch 1 operation expansion: Slack, Google Sheets, GitHub, and Stripe.

Verifies newly implemented operations, parameter schemas, negative validation guards,
and definition integrity in ConnectorRegistry.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.connectors import get_registry, register_builtin_connectors, ConnectorError
from app.connectors.slack_connector import SlackConnector
from app.connectors.google_sheets_connector import GoogleSheetsConnector
from app.connectors.github_connector import GitHubConnector
from app.connectors.stripe_connector import StripeConnector


def _make_response(data: dict[str, Any], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


# =============================================================================
# 1. SLACK OPERATIONS (add_reaction, get_user_by_email)
# =============================================================================

@pytest.mark.asyncio
async def test_slack_add_reaction_success():
    conn = SlackConnector()
    with patch.object(conn._provider, "request_slack", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({"ok": True})
        res = await conn.op_execute(
            "add_reaction",
            {"channel": "C12345", "timestamp": "1234567890.123456", "name": "thumbsup"},
            context={"credentials": {"slack": {"bot_token": "xoxb-mock-token"}}},
        )
        assert res["ok"] is True
        assert res["channel"] == "C12345"
        assert res["reaction"] == "thumbsup"


@pytest.mark.asyncio
async def test_slack_add_reaction_missing_params():
    conn = SlackConnector()
    with pytest.raises(ConnectorError) as exc_info:
        await conn.op_execute(
            "add_reaction",
            {"channel": "", "timestamp": "", "name": ""},
            context={"credentials": {"slack": {"bot_token": "xoxb-mock-token"}}},
        )
    assert "requires channel, timestamp, and emoji name" in str(exc_info.value)


@pytest.mark.asyncio
async def test_slack_get_user_by_email():
    conn = SlackConnector()
    with patch.object(conn._provider, "request_slack", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "ok": True,
            "user": {
                "id": "U98765",
                "name": "johndoe",
                "real_name": "John Doe",
                "profile": {"email": "john@example.com"},
                "tz": "America/New_York",
                "is_admin": True,
            },
        })
        res = await conn.op_execute(
            "get_user_by_email",
            {"email": "john@example.com"},
            context={"credentials": {"slack": {"bot_token": "xoxb-mock-token"}}},
        )
        assert res["id"] == "U98765"
        assert res["email"] == "john@example.com"
        assert res["is_admin"] is True


# =============================================================================
# 2. GOOGLE SHEETS OPERATIONS (clear, get_info)
# =============================================================================

@pytest.mark.asyncio
async def test_google_sheets_clear_range():
    conn = GoogleSheetsConnector()
    with patch.object(conn._provider, "authorized_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "spreadsheetId": "sheet_abc123",
            "clearedRange": "Sheet1!A1:B10",
        })
        res = await conn.op_execute(
            "clear",
            {"spreadsheet_id": "sheet_abc123", "range": "Sheet1!A1:B10"},
            context={"credentials": {"google_sheets": {"refresh_token": "mock_refresh"}}},
        )
        assert res["cleared"] is True
        assert res["range"] == "Sheet1!A1:B10"


@pytest.mark.asyncio
async def test_google_sheets_get_spreadsheet_info():
    conn = GoogleSheetsConnector()
    with patch.object(conn._provider, "authorized_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "properties": {"title": "Q3 Budget", "locale": "en_US"},
            "sheets": [
                {"properties": {"sheetId": 0, "title": "Summary", "index": 0}},
                {"properties": {"sheetId": 1, "title": "Details", "index": 1}},
            ],
        })
        res = await conn.op_execute(
            "get_info",
            {"spreadsheet_id": "sheet_abc123"},
            context={"credentials": {"google_sheets": {"refresh_token": "mock_refresh"}}},
        )
        assert res["spreadsheet_id"] == "sheet_abc123"
        assert res["title"] == "Q3 Budget"
        assert res["sheet_count"] == 2
        assert res["sheets"][0]["title"] == "Summary"


# =============================================================================
# 3. GITHUB OPERATIONS (get_issue, close_issue)
# =============================================================================

@pytest.mark.asyncio
async def test_github_get_issue():
    conn = GitHubConnector()
    with patch.object(conn._provider, "request_github", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "number": 42,
            "title": "Fix memory leak in worker",
            "body": "Detailed repro instructions",
            "state": "open",
            "html_url": "https://github.com/org/repo/issues/42",
            "user": {"login": "octocat"},
            "comments": 3,
        })
        res = await conn.op_execute(
            "get_issue",
            {"owner": "org", "repo": "repo", "issue_number": 42},
            context={"credentials": {"github": {"access_token": "ghp_mock_token"}}},
        )
        assert res["number"] == 42
        assert res["title"] == "Fix memory leak in worker"
        assert res["user"] == "octocat"
        assert res["state"] == "open"


@pytest.mark.asyncio
async def test_github_close_issue():
    conn = GitHubConnector()
    with patch.object(conn._provider, "request_github", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "number": 42,
            "state": "closed",
            "html_url": "https://github.com/org/repo/issues/42",
        })
        res = await conn.op_execute(
            "close_issue",
            {"owner": "org", "repo": "repo", "issue_number": 42},
            context={"credentials": {"github": {"access_token": "ghp_mock_token"}}},
        )
        assert res["number"] == 42
        assert res["closed"] is True
        assert res["state"] == "closed"


# =============================================================================
# 4. STRIPE OPERATIONS (create_refund, get_payment_intent)
# =============================================================================

@pytest.mark.asyncio
async def test_stripe_create_refund():
    conn = StripeConnector()
    with patch.object(conn._provider, "request_stripe", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "id": "re_12345",
            "payment_intent": "pi_98765",
            "amount": 2500,
            "currency": "usd",
            "status": "succeeded",
        })
        res = await conn.op_execute(
            "create_refund",
            {"payment_intent": "pi_98765", "amount": 2500, "reason": "requested_by_customer"},
            context={"credentials": {"stripe": {"secret_key": "sk_test_mock"}}},
        )
        assert res["refund_id"] == "re_12345"
        assert res["amount"] == 2500
        assert res["status"] == "succeeded"


@pytest.mark.asyncio
async def test_stripe_get_payment_intent():
    conn = StripeConnector()
    with patch.object(conn._provider, "request_stripe", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = _make_response({
            "id": "pi_98765",
            "amount": 5000,
            "currency": "usd",
            "status": "succeeded",
            "customer": "cus_abc",
            "client_secret": "pi_98765_secret_xyz",
        })
        res = await conn.op_execute(
            "get_payment_intent",
            {"payment_intent_id": "pi_98765"},
            context={"credentials": {"stripe": {"secret_key": "sk_test_mock"}}},
        )
        assert res["intent_id"] == "pi_98765"
        assert res["amount"] == 5000
        assert res["customer"] == "cus_abc"


# =============================================================================
# 5. REGISTRY DEFINITION CONTRACT CHECKS
# =============================================================================

def test_registry_has_expanded_operations():
    reg = get_registry()

    slack_defn = reg.get_definition("slack")
    assert "add_reaction" in slack_defn.operations
    assert "get_user_by_email" in slack_defn.operations

    sheets_defn = reg.get_definition("google_sheets")
    assert "clear" in sheets_defn.operations
    assert "get_info" in sheets_defn.operations

    github_defn = reg.get_definition("github")
    assert "get_issue" in github_defn.operations
    assert "close_issue" in github_defn.operations

    stripe_defn = reg.get_definition("stripe")
    assert "create_refund" in stripe_defn.operations
    assert "get_payment_intent" in stripe_defn.operations
