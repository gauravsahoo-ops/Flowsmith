from __future__ import annotations

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from app.main import CSRFMiddleware

# Create test app with strict allowed origins
test_app = FastAPI()
test_app.add_middleware(CSRFMiddleware, allowed_origins=["http://localhost:8000"])

@test_app.post("/test-action")
def dummy_action():
    return {"ok": True}

client = TestClient(test_app, raise_server_exceptions=False)


def test_csrf_blocks_unauthorized_external_origin():
    """An external website trying to post to Flowsmith must be blocked by CSRF."""
    response = client.post(
        "/test-action",
        json={"data": "test"},
        headers={"Origin": "https://evil-hacker-site.com", "Host": "localhost:8000"},
    )
    assert response.status_code == 403
    assert "CSRF validation failed: cross-origin request rejected" in response.text


def test_csrf_allows_configured_allowed_origin():
    """An origin explicitly in allowed_origins must pass."""
    response = client.post(
        "/test-action",
        json={"data": "test"},
        headers={"Origin": "http://localhost:8000", "Host": "localhost:8000"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_csrf_allows_same_host_origin():
    """When accessing via server IP, Origin matching Host header must be allowed as same-origin."""
    server_ip = "192.168.1.150:8000"
    response = client.post(
        "/test-action",
        json={"data": "test"},
        headers={
            "Host": server_ip,
            "Origin": f"http://{server_ip}",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_csrf_allows_x_forwarded_host():
    """When behind a reverse proxy, X-Forwarded-Host matching Origin must be allowed."""
    domain = "automation.mycompany.com"
    response = client.post(
        "/test-action",
        json={"data": "test"},
        headers={
            "X-Forwarded-Host": domain,
            "Host": "internal-docker:8000",
            "Origin": f"https://{domain}",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}

