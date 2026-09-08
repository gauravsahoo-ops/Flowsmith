"""Auth endpoint tests (spec 51.4: authentication, validation, errors)."""

from __future__ import annotations

import pytest

from tests.test_api.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """Module-level throttle singleton would leak IP-key lockouts across
    tests; start each test with a clean slate."""
    from app.api.auth import login_throttle

    login_throttle.reset()
    yield
    login_throttle.reset()

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"


def test_register_succeeds(client):
    resp = client.post("/api/auth/register", json={"email": "a@b.com", "password": "Password123!"})
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["token"]
    assert data["user"]["email"] == "a@b.com"


def test_register_duplicate_email_conflicts(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "Password123!"})
    resp = client.post("/api/auth/register", json={"email": "a@b.com", "password": "Password123!"})
    assert resp.status_code == 409


def test_register_invalid_email_rejected(client):
    resp = client.post("/api/auth/register", json={"email": "not-an-email", "password": "Password123!"})
    assert resp.status_code == 422


def test_register_short_password_rejected(client):
    resp = client.post("/api/auth/register", json={"email": "a@b.com", "password": "short"})
    assert resp.status_code == 422


def test_login_succeeds(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "Password123!"})
    resp = client.post("/api/auth/login", json={"email": "a@b.com", "password": "Password123!"})
    assert resp.status_code == 200
    assert resp.json()["data"]["token"]


def test_login_wrong_password_rejected(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "password": "Password123!"})
    resp = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong-password"})
    assert resp.status_code == 401


def test_protected_route_requires_token(client):
    assert client.get("/api/workflows").status_code == 401


def test_protected_route_rejects_garbage_token(client):
    resp = client.get("/api/workflows", headers=auth_headers("garbage.token.here"))
    assert resp.status_code == 401

# ---- Input normalization (Phase 42) ----

def test_register_then_login_with_case_and_whitespace_variants(client):
    """Signup with padded/mixed-case values; later login with clean,
    differently-cased values must succeed."""
    reg = client.post(
        "/api/auth/register",
        json={"email": "  Mixed@Example.COM ", "password": "  Sup3rSecret!  "},
    )
    assert reg.status_code == 201, reg.text

    # Login with the exact same padded form (autofill case)
    r1 = client.post(
        "/api/auth/login",
        json={"email": "  Mixed@Example.COM ", "password": "  Sup3rSecret!  "},
    )
    assert r1.status_code == 200, r1.text

    # Login with the clean, lower-cased form (manual typing case)
    r2 = client.post(
        "/api/auth/login",
        json={"email": "mixed@example.com", "password": "Sup3rSecret!"},
    )
    assert r2.status_code == 200, r2.text


def test_duplicate_register_conflicts_across_casing_and_padding(client):
    body = {"email": "Dup@Example.com", "password": "Whatever1!"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    dup = client.post(
        "/api/auth/register",
        json={"email": "  dup@example.com ", "password": "Other22!"},
    )
    assert dup.status_code == 409


def test_wrong_password_still_rejected_after_normalization(client):
    client.post("/api/auth/register", json={"email": "norm@x.com", "password": "Right1!"})
    bad = client.post("/api/auth/login", json={"email": " norm@x.com", "password": " Wrong1!"})
    assert bad.status_code == 401
