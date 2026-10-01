"""Integration tests for /api/llm endpoints."""

import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.api.auth import get_current_user
from app.models import User


class MockUser:
    id = "usr_test_llm"
    email = "test_llm@flowsmith.io"
    is_active = True
    role = "admin"


@pytest.fixture
def auth_client():
    app.dependency_overrides[get_current_user] = lambda: MockUser()
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_list_providers_endpoint(auth_client):
    res = auth_client.get("/api/llm/providers")
    assert res.status_code == 200
    body = res.json()
    assert "data" in body
    data = body["data"]
    assert data["total"] >= 180
    assert "Major Providers" in data["categories"]
    assert len(data["providers"]) >= 180

    # Search filter via query param
    search_res = auth_client.get("/api/llm/providers?q=groq")
    assert search_res.status_code == 200
    search_data = search_res.json()["data"]
    p_names = [p["provider_id"] for p in search_data["providers"]]
    assert "groq" in p_names


def test_get_single_provider(auth_client):
    res = auth_client.get("/api/llm/providers/openai")
    assert res.status_code == 200
    p = res.json()["data"]
    assert p["provider_id"] == "openai"
    assert p["display_name"] == "OpenAI"
    assert len(p["model_catalog"]) >= 4
    assert len(p["credential_fields"]) >= 1


def test_test_connection_endpoint(auth_client):
    with respx.mock(base_url="https://api.openai.com/v1") as mock:
        mock.get("/models").respond(200, json={"data": [{"id": "gpt-4o"}]})
        payload = {
            "provider_id": "openai",
            "data": {
                "api_key": "sk-mock-key",
                "base_url": "https://api.openai.com/v1"
            }
        }
        res = auth_client.post("/api/llm/test-connection", json=payload)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["ok"] is True
        assert "Successfully connected" in data["message"]


def test_discover_models_endpoint(auth_client):
    with respx.mock(base_url="https://api.deepseek.com/v1") as mock:
        mock.get("/models").respond(200, json={
            "data": [
                {"id": "deepseek-chat", "name": "DeepSeek-V3"},
                {"id": "deepseek-reasoner", "name": "DeepSeek-R1"}
            ]
        })
        payload = {
            "provider_id": "deepseek",
            "data": {
                "api_key": "sk-deepseek-key",
                "base_url": "https://api.deepseek.com/v1"
            }
        }
        res = auth_client.post("/api/llm/discover-models", json=payload)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["provider_id"] == "deepseek"
        assert data["count"] == 2
        models = data["models"]
        r1 = next(m for m in models if m["id"] == "deepseek-reasoner")
        assert r1["capabilities"]["reasoning"] is True
