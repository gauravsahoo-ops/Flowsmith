import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.connectors import ConnectorError
from app.connectors.airtable_connector import AirtableConnector
from app.connectors.github_connector import GitHubConnector
from app.connectors.hubspot_connector import HubSpotConnector
from app.connectors.notion_connector import NotionConnector
from app.connectors.postgres_connector import PostgresConnector
from app.connectors.redis_connector import RedisConnector
from app.connectors.mysql_connector import MySQLConnector
from app.connectors.mongodb_connector import MongoDBConnector
from app.connectors.slack_connector import SlackConnector
from app.connectors.stripe_connector import StripeConnector


ACTION_PROBES = [
    (StripeConnector, "request_stripe", {"secret_key": "sk_test_x"}),
    (GitHubConnector, "request_github", {"access_token": "ghp_x"}),
    (SlackConnector, "request_slack", {"bot_token": "xoxb-x"}),
    (NotionConnector, "request_notion", {"integration_token": "secret_x"}),
    (AirtableConnector, "request_airtable", {"personal_access_token": "pat_x"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_cls, method, creds", ACTION_PROBES)
async def test_action_connector_live_probe_success(connector_cls, method, creds):
    conn = connector_cls()
    setattr(conn._provider, method, AsyncMock(return_value=MagicMock(status_code=200)))
    res = await conn.test_connection(creds)
    assert res["ok"] is True
    assert "Successfully connected" in res["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_cls, method, creds", ACTION_PROBES)
async def test_action_connector_live_probe_auth_failure(connector_cls, method, creds):
    conn = connector_cls()
    setattr(
        conn._provider,
        method,
        AsyncMock(side_effect=ConnectorError("auth failed", code="CONNECTOR_AUTH_FAILED")),
    )
    res = await conn.test_connection(creds)
    assert res["ok"] is False
    assert "connection test failed" in res["message"].lower()


@pytest.mark.asyncio
async def test_hubspot_connector_live_probe_success():
    conn = HubSpotConnector()
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    conn._provider.request = AsyncMock(return_value=mock_resp)
    res = await conn.test_connection({"private_token": "pat_test_12345"})

    assert res["ok"] is True
    assert "Successfully connected to HubSpot" in res["message"]
    assert res["latency_ms"] >= 0.0


@pytest.mark.asyncio
async def test_hubspot_connector_live_probe_auth_failure():
    conn = HubSpotConnector()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = '{"message": "Invalid token"}'

    conn._provider.request = AsyncMock(return_value=mock_resp)
    res = await conn.test_connection({"private_token": "expired_token"})

    assert res["ok"] is False
    assert "status 401" in res["message"]


@pytest.mark.asyncio
async def test_postgres_connector_live_probe_success():
    conn = PostgresConnector()
    conn._provider.query = AsyncMock(return_value={"rows": [{"ping": 1}]})

    res = await conn.test_connection({"dsn": "postgresql://test:test@localhost:5432/test"})
    assert res["ok"] is True
    assert "SELECT 1 OK" in res["message"]


@pytest.mark.asyncio
async def test_postgres_connector_live_probe_failure():
    conn = PostgresConnector()
    conn._provider.query = AsyncMock(side_effect=Exception("Database unreachable"))

    res = await conn.test_connection({"dsn": "postgresql://test:test@localhost:5432/test"})
    assert res["ok"] is False
    assert "Database unreachable" in res["message"]


@pytest.mark.asyncio
async def test_redis_connector_live_probe_success():
    conn = RedisConnector()
    conn._provider._run = AsyncMock(return_value=True)

    res = await conn.test_connection({"uri": "redis://localhost:6379"})
    assert res["ok"] is True
    assert "PONG received" in res["message"]


@pytest.mark.asyncio
async def test_redis_connector_live_probe_failure():
    conn = RedisConnector()
    conn._provider._run = AsyncMock(side_effect=Exception("Connection refused"))

    res = await conn.test_connection({"uri": "redis://localhost:6379"})
    assert res["ok"] is False
    assert "Connection refused" in res["message"]


@pytest.mark.asyncio
async def test_mysql_connector_live_probe_success():
    conn = MySQLConnector()
    conn._provider.query = AsyncMock(return_value={"rows": [{"ping": 1}]})

    res = await conn.test_connection({"dsn": "mysql://user:pass@localhost:3306/db"})
    assert res["ok"] is True
    assert "SELECT 1 OK" in res["message"]


@pytest.mark.asyncio
async def test_mongodb_connector_live_probe_success():
    conn = MongoDBConnector()
    conn._provider.ping = AsyncMock(return_value={"ok": 1.0})

    res = await conn.test_connection({"uri": "mongodb://localhost:27017"})
    assert res["ok"] is True
    assert "ping OK" in res["message"]
