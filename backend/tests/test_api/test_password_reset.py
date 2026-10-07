"""Self-service password reset (Phase 42).

Covers: email issuance (the response never carries the link), unknown-
email anti-enumeration, password change + single-use tokens, expiry,
weak-password policy, and lockout clearing on successful reset.
"""

from __future__ import annotations

import time

import pytest

from tests.test_api.conftest import auth_headers, register


@pytest.fixture(autouse=True)
def reset_links(monkeypatch):
    """Capture reset links delivered to _send_reset_email.

    The API no longer returns the link in its response (audit fix), and
    the DB stores only the SHA-256 hash — so tests intercept the email
    hand-off instead.
    """
    from app.api import auth as auth_module

    links: list[str] = []

    def _capture(to: str, link: str) -> bool:
        links.append(link)
        return True

    monkeypatch.setattr(auth_module, "_send_reset_email", _capture)
    return links


def _request_reset(client, email: str):
    return client.post("/api/auth/forgot-password", json={"email": email})


def _expire_latest_token(email: str):
    """Mark the user's latest reset token as expired (single session)."""
    from datetime import UTC, datetime, timedelta

    from app.db import get_session
    from app.models import PasswordResetToken, User

    db = get_session()
    try:
        user = db.query(User).filter_by(email=email).first()
        row = (
            db.query(PasswordResetToken)
            .filter_by(user_id=user.id)
            .order_by(PasswordResetToken.id.desc())
            .first()
        )
        row.expires_at = datetime.now(UTC) - timedelta(seconds=5)
        db.commit()
    finally:
        db.close()


def _wait_terminal(client, headers, eid, timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/api/executions/{eid}", headers=headers).json()
        if "data" in body and body["data"]["status"] not in ("queued", "running", "cancelling"):
            return body["data"]
        time.sleep(0.05)
    raise AssertionError("execution did not finish")


# ----------------------------------------------------------------------
# Request flow
# ----------------------------------------------------------------------

def test_forgot_password_always_200_even_for_unknown_email(client):
    resp = _request_reset(client, "ghost@flowsmith.dev")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["sent"] is True
    assert "dev_reset_link" not in body


def test_forgot_password_emails_link_without_returning_it(client, reset_links):
    register(client, email="resetme@flowsmith.dev")
    r = _request_reset(client, "resetme@flowsmith.dev")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["sent"] is True
    assert "dev_reset_link" not in body
    assert reset_links and "token=" in reset_links[-1]


# ----------------------------------------------------------------------
# Reset flow
# ----------------------------------------------------------------------

def test_reset_changes_password_and_single_use(client, reset_links):
    email = "cycle@flowsmith.dev"
    register(client, email=email)

    _request_reset(client, email)
    token = reset_links[-1].split("token=")[1]

    new = client.post("/api/auth/reset-password", json={"token": token, "new_password": "BrandNew2!"})
    assert new.status_code == 200

    assert client.post("/api/auth/login", json={"email": email, "password": "OldPass1!"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "BrandNew2!"}).status_code == 200

    # Weak password -> 422 (policy), token NOT consumed by that attempt.
    weak = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "Third3!"}
    )
    assert weak.status_code == 422

    # Token single-use: replay after success -> 400.
    replay = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "Third33!"},
    )
    assert replay.status_code == 400


def test_reset_revokes_outstanding_bearer_tokens(client, reset_links):
    """A password reset must kill sessions issued before it (S2)."""
    from tests.test_api.conftest import auth_headers

    email = "revoke@flowsmith.dev"
    reg = register(client, email=email)
    old_headers = auth_headers(reg["token"])

    # Ensure the old token's iat lands in a strictly earlier second than the
    # reset (iat is second-granularity).
    time.sleep(1.1)

    assert client.get("/api/auth/me", headers=old_headers).status_code == 200

    _request_reset(client, email)
    token = reset_links[-1].split("token=")[1]
    resp = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "Revoked9!"}
    )
    assert resp.status_code == 200

    # Old bearer token: dead on every gated route.
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401

    # Fresh login works and the new token is valid.
    login = client.post("/api/auth/login", json={"email": email, "password": "Revoked9!"})
    assert login.status_code == 200
    new_token = login.json()["data"]["token"]
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code
        == 200
    )


def test_expired_token_rejected(client, reset_links):
    from datetime import UTC, datetime, timedelta

    from app.db import get_session
    from app.models import PasswordResetToken, User

    email = "expired@flowsmith.dev"
    register(client, email=email)
    _request_reset(client, email)
    token = reset_links[-1].split("token=")[1]

    db = get_session()
    try:
        row = (
            db.query(PasswordResetToken)
            .order_by(PasswordResetToken.id.desc())
            .first()
        )
        row.expires_at = datetime.now(UTC) - timedelta(seconds=5)
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "NewPass3!"}
    )
    assert resp.status_code == 400


def test_weak_new_password_rejected(client, reset_links):
    email = "weak@flowsmith.dev"
    register(client, email=email)
    _request_reset(client, email)
    token = reset_links[-1].split("token=")[1]

    resp = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "short"}
    )
    assert resp.status_code == 422


def test_reset_clears_login_lockout(client, reset_links):
    from app.api.auth import login_throttle
    from app.config import get_settings

    email = "locked@flowsmith.dev"
    register(client, email=email)

    for _ in range(get_settings().login_max_attempts):
        client.post(
            "/api/auth/login", json={"email": email, "password": "Wrong1!x"}
        )
    locked = client.post(
        "/api/auth/login", json={"email": email, "password": "Start3!x"}
    )
    assert locked.status_code == 429

    _request_reset(client, email)
    token = reset_links[-1].split("token=")[1]
    resp = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "Fresh4!x"}
    )
    assert resp.status_code == 200

    ok = client.post("/api/auth/login", json={"email": email, "password": "Fresh4!x"})
    assert ok.status_code == 200


def test_forgot_password_prefers_public_url_over_host_header(client, reset_links, monkeypatch):
    """H3: reset links must never be derived from a forged Host header."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_url", "https://flowsmith.example")
    register(client, "reset_host_a@test.com")
    resp = client.post(
        "/api/auth/forgot-password",
        json={"email": "reset_host_a@test.com"},
        headers={"Host": "evil.example"},
    )
    assert resp.status_code == 200
    assert reset_links, "reset email should be sent"
    assert reset_links[-1].startswith("https://flowsmith.example/")
    assert "evil.example" not in reset_links[-1]


def test_forgot_password_suppressed_without_public_url_in_production(client, reset_links, monkeypatch):
    """H3: outside development with no PUBLIC_URL, no link may be built."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "public_url", "")
    monkeypatch.setattr(settings, "app_env", "production")
    register(client, "reset_host_b@test.com")
    resp = client.post(
        "/api/auth/forgot-password",
        json={"email": "reset_host_b@test.com"},
        headers={"Host": "evil.example"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["sent"] is True
    assert reset_links == []
