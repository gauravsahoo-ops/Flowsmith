import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.connectors.parity_connectors import ParityConnector


@pytest.mark.asyncio
async def test_parity_connector_test_connection_empty_creds():
    conn = ParityConnector("test_api", "Test API")
    res = await conn.test_connection({})
    assert res["ok"] is False
    assert "No credentials provided" in res["message"]


@pytest.mark.asyncio
async def test_parity_connector_test_connection_ssrf_blocked():
    conn = ParityConnector("test_api", "Test API")
    res = await conn.test_connection({
        "endpoint_url": "http://169.254.169.254/latest/meta-data",
        "api_key": "secret",
    })
    assert res["ok"] is False
    assert "SSRF" in res["message"]


@pytest.mark.asyncio
async def test_parity_connector_test_connection_unsupported_scheme():
    conn = ParityConnector("test_api", "Test API")
    res = await conn.test_connection({
        "endpoint_url": "ftp://files.example.com",
        "api_key": "secret",
    })
    assert res["ok"] is False
    assert "Unsupported URL scheme" in res["message"]


@pytest.mark.asyncio
async def test_parity_connector_test_connection_live_probe_success():
    conn = ParityConnector("test_api", "Test API")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-ratelimit-remaining": "4950"}

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=mock_client):
        res = await conn.test_connection({
            "endpoint_url": "https://api.example.com/v1/ping",
            "api_key": "valid_token_12345",
        })

    assert res["ok"] is True
    assert res["status_code"] == 200
    assert "Successfully verified" in res["message"]
    assert res["latency_ms"] >= 0.0
    assert res["rate_limit_remaining"] == "4950"


@pytest.mark.asyncio
async def test_parity_connector_test_connection_live_probe_auth_rejected():
    conn = ParityConnector("test_api", "Test API")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.headers = {}

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    with patch("app.security.safe_http_client.get_safe_http_client", return_value=mock_client):
        res = await conn.test_connection({
            "endpoint_url": "https://api.example.com/v1/ping",
            "api_key": "bad_token",
        })

    assert res["ok"] is False
    assert res["status_code"] == 401
    assert "Authentication rejected" in res["message"]


@pytest.mark.asyncio
async def test_parity_connector_test_connection_no_url_valid_token():
    conn = ParityConnector("test_api", "Test API")
    res = await conn.test_connection({
        "api_key": "test_api_key_secret_123",
        "environment": "production",
    })
    assert res["ok"] is True
    assert "validated against connector schema" in res["message"]
    assert "api_key" in res["validated_fields"]
