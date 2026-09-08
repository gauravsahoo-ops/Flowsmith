"""Self-service password reset (Phase 42).

Covers: dev-link issuance, unknown-email anti-enumeration, password
change + single-use tokens, expiry, weak-password policy, and lockout
clearing on successful reset.
"""

from __future__ import annotations

import time

import pytest

from tests.test_api.conftest import auth_headers, register


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


def test_forgot_password_returns_dev_link(client):
    register(client, email="resetme@flowsmith.dev")
    r = _request_reset(client, "resetme@flowsmith.dev")
    assert r.status_code == 200
    link = r.json()["data"].get("dev_reset_link")
    assert link and "token=" in link


# ----------------------------------------------------------------------
# Reset flow
# ----------------------------------------------------------------------

def test_reset_changes_password_and_single_use(client):
    email = "cycle@flowsmith.dev"
    register(client, email=email)

    token = _request_reset(client, email).json()["data"]["dev_reset_link"].split("token=")[1]

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


def test_expired_token_rejected(client):
    from datetime import UTC, datetime, timedelta

    from app.db import get_session
    from app.models import PasswordResetToken, User

    email = "expired@flowsmith.dev"
    register(client, email=email)
    r = _request_reset(client, email)
    token = r.json()["data"]["dev_reset_link"].split("token=")[1]

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


def test_weak_new_password_rejected(client):
    email = "weak@flowsmith.dev"
    register(client, email=email)
    token = _request_reset(client, email).json()["data"]["dev_reset_link"].split("token=")[1]

    resp = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "short"}
    )
    assert resp.status_code == 422


def test_reset_clears_login_lockout(client):
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

    r = _request_reset(client, email)
    token = r.json()["data"]["dev_reset_link"].split("token=")[1]
    resp = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "Fresh4!x"}
    )
    assert resp.status_code == 200

    ok = client.post("/api/auth/login", json={"email": email, "password": "Fresh4!x"})
    assert ok.status_code == 200
