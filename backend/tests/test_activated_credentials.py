import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.credentials.registry import (
    validate_data,
    is_implemented,
    list_types,
    CREDENTIAL_TYPES,
)
from app.ai.providers.groq_provider import GroqProvider
from app.ai.providers.deepseek_provider import DeepSeekProvider
from app.providers.microsoft_graph import MicrosoftGraphProviderClient


def test_groq_credential_validation():
    assert is_implemented("groq") is True
    # Valid Groq credential
    validated = validate_data("groq", {"api_key": "gsk_test_token_12345"})
    assert validated["api_key"] == "gsk_test_token_12345"

    # Missing api_key must fail
    with pytest.raises(Exception):
        validate_data("groq", {})

    with pytest.raises(Exception):
        validate_data("groq", {"api_key": ""})


def test_deepseek_credential_validation():
    assert is_implemented("deepseek") is True
    # Valid DeepSeek credential
    validated = validate_data("deepseek", {"api_key": "sk_test_deepseek_token"})
    assert validated["api_key"] == "sk_test_deepseek_token"

    # Missing api_key must fail
    with pytest.raises(Exception):
        validate_data("deepseek", {})

    with pytest.raises(Exception):
        validate_data("deepseek", {"api_key": ""})


def test_sharepoint_credential_validation():
    assert is_implemented("sharepoint") is True
    # Valid SharePoint credential
    validated = validate_data("sharepoint", {
        "access_token": "eyJ0eXAi...",
        "site_url": "https://tenant.sharepoint.com/sites/team",
        "tenant_id": "tenant-uuid-1234",
    })
    assert validated["access_token"] == "eyJ0eXAi..."
    assert validated["site_url"] == "https://tenant.sharepoint.com/sites/team"

    # Missing access_token must fail
    with pytest.raises(Exception):
        validate_data("sharepoint", {"site_url": "https://tenant.sharepoint.com"})


def test_onedrive_credential_validation():
    assert is_implemented("onedrive") is True
    # Valid OneDrive credential
    validated = validate_data("onedrive", {
        "access_token": "eyJ0eXAi...",
        "tenant_id": "tenant-uuid-1234",
    })
    assert validated["access_token"] == "eyJ0eXAi..."

    # Missing access_token must fail
    with pytest.raises(Exception):
        validate_data("onedrive", {})


def test_groq_ai_provider_execution():
    provider = GroqProvider()
    url, headers, body = provider._prepare_request(
        messages=[{"role": "user", "content": "Hello Groq"}],
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        max_tokens=100,
        tools=None,
        tool_choice="none",
        response_format=None,
        api_key="gsk_mock_api_key",
        base_url="",
        extra_headers=None,
    )
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer gsk_mock_api_key"
    assert body["model"] == "llama-3.3-70b-versatile"
    assert body["messages"][0]["content"] == "Hello Groq"


def test_deepseek_ai_provider_execution():
    provider = DeepSeekProvider()
    url, headers, body = provider._prepare_request(
        messages=[{"role": "user", "content": "Explain quantum computing"}],
        model="deepseek-chat",
        temperature=0.0,
        max_tokens=256,
        tools=None,
        tool_choice="none",
        response_format=None,
        api_key="sk_mock_deepseek_key",
        base_url="",
        extra_headers=None,
    )
    assert url == "https://api.deepseek.com/chat/completions"
    assert headers["Authorization"] == "Bearer sk_mock_deepseek_key"
    assert body["model"] == "deepseek-chat"
    assert body["messages"][0]["content"] == "Explain quantum computing"


@pytest.mark.asyncio
async def test_microsoft_graph_provider_test_connection_success():
    client = MicrosoftGraphProviderClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "token_123", "expires_in": 3600}

    mock_http = AsyncMock()
    mock_http.__aenter__.return_value = mock_http
    mock_http.request.return_value = mock_resp

    with patch("app.providers.microsoft_graph.get_safe_http_client", return_value=mock_http):
        res = await client.test_connection({
            "tenant_id": "tenant-123",
            "client_id": "client-456",
            "client_secret": "secret-789",
        })

    assert res["ok"] is True
    assert "Connected to Microsoft Graph successfully" in res["message"]


@pytest.mark.asyncio
async def test_microsoft_graph_provider_test_connection_auth_error():
    client = MicrosoftGraphProviderClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = '{"error": "invalid_client", "error_description": "Bad secret"}'

    mock_http = AsyncMock()
    mock_http.__aenter__.return_value = mock_http
    mock_http.request.return_value = mock_resp

    with patch("app.providers.microsoft_graph.get_safe_http_client", return_value=mock_http):
        res = await client.test_connection({
            "tenant_id": "tenant-123",
            "client_id": "client-456",
            "client_secret": "bad-secret",
        })

    assert res["ok"] is False
    assert "Microsoft rejected the app credentials" in res["message"]
