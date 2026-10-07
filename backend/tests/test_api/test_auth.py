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


def test_x_authorization_header_accepted_with_proxy_basic_auth(client):
    reg = client.post("/api/auth/register", json={"email": "proxy@example.com", "password": "ProxyPassword1!"})
    token = reg.json()["data"]["token"]
    # When an upstream proxy sends Basic Auth in Authorization, X-Authorization carries Bearer
    resp = client.get("/api/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz", "X-Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == "proxy@example.com"


def _smtp_settings(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(s, "smtp_port", 587)
    monkeypatch.setattr(s, "smtp_user", "smtpuser")
    monkeypatch.setattr(s, "smtp_password", "s3cr3t")
    monkeypatch.setattr(s, "mail_from", "no-reply@example.test")
    monkeypatch.setattr(s, "smtp_use_tls", False)
    monkeypatch.setattr(s, "smtp_starttls", True)


def test_starttls_failure_aborts_before_cleartext_auth(monkeypatch):
    """Regression: a failed STARTTLS negotiation used to be swallowed,
    then login()+send_message() ran over plaintext (SMTP password and
    reset link exposed). It must fail fast instead."""
    import smtplib

    from app.api.auth import _send_reset_email

    _smtp_settings(monkeypatch)
    calls = {"login": [], "send": []}

    class FailingSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            raise smtplib.SMTPException("TLS negotiation failed")

        def login(self, user, password):
            calls["login"].append(user)

        def send_message(self, msg):
            calls["send"].append(msg)

    monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
    sent = _send_reset_email("user@example.test", "http://reset/token")
    assert sent is False
    assert calls["login"] == []
    assert calls["send"] == []


def test_starttls_success_still_delivers(monkeypatch):
    """Control: with STARTTLS succeeding, delivery proceeds normally."""
    from app.api.auth import _send_reset_email

    _smtp_settings(monkeypatch)
    calls = {"starttls": 0, "login": [], "send": []}

    class WorkingSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            calls["starttls"] += 1

        def login(self, user, password):
            calls["login"].append(user)

        def send_message(self, msg):
            calls["send"].append(msg)

    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", WorkingSMTP)
    sent = _send_reset_email("user@example.test", "http://reset/token")
    assert sent is True
    assert calls["starttls"] == 1
    assert calls["login"] == ["smtpuser"]
    assert len(calls["send"]) == 1

