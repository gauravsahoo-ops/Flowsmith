"""TOTP MFA enrollment, challenge exchange, replay, and disable tests."""

from __future__ import annotations

import jwt as pyjwt
import pytest

from app.security.totp import code_at, current_step
from tests.test_api.conftest import auth_headers, register

PASSWORD = "Password123!"


def _code(secret: str, offset: int = 0) -> str:
    return code_at(secret, current_step() + offset)


def _setup_and_enable(client, token: str) -> tuple[str, list[str]]:
    setup = client.post(
        "/api/auth/mfa/setup",
        json={"password": PASSWORD},
        headers=auth_headers(token),
    )
    assert setup.status_code == 200, setup.text
    secret = setup.json()["data"]["secret"]
    enable = client.post(
        "/api/auth/mfa/enable",
        json={"password": PASSWORD, "code": _code(secret)},
        headers=auth_headers(token),
    )
    assert enable.status_code == 200, enable.text
    return secret, enable.json()["data"]["recovery_codes"]


def test_mfa_enrollment_login_challenge_and_replay_rejection(client):
    data = register(client, "mfa@example.com", PASSWORD)
    token = data["token"]
    headers = auth_headers(token)

    status = client.get("/api/auth/mfa", headers=headers)
    assert status.status_code == 200
    assert status.json()["data"]["enabled"] is False
    assert status.json()["data"]["configured"] is False

    setup = client.post(
        "/api/auth/mfa/setup",
        json={"password": PASSWORD},
        headers=headers,
    )
    assert setup.status_code == 200, setup.text
    payload = setup.json()["data"]
    secret = payload["secret"]
    assert payload["otpauth_uri"].startswith("otpauth://totp/")
    assert f"secret={secret}" in payload["otpauth_uri"]
    assert not secret.startswith("k0:")

    from app.db import get_session
    from app.models import User

    db = get_session()
    try:
        stored = db.get(User, data["user"]["id"])
        assert stored is not None
        assert stored.mfa_secret and stored.mfa_secret != secret
        assert stored.mfa_enabled is False
    finally:
        db.close()

    wrong_enable = client.post(
        "/api/auth/mfa/enable",
        json={"password": PASSWORD, "code": "000000"},
        headers=headers,
    )
    assert wrong_enable.status_code == 400

    enable = client.post(
        "/api/auth/mfa/enable",
        json={"password": PASSWORD, "code": _code(secret)},
        headers=headers,
    )
    assert enable.status_code == 200, enable.text
    recovery_codes = enable.json()["data"]["recovery_codes"]
    assert len(recovery_codes) == 10
    assert len(set(recovery_codes)) == 10

    login = client.post(
        "/api/auth/login",
        json={"email": "mfa@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    challenge = login.json()["data"]
    assert challenge["mfa_required"] is True
    assert challenge["challenge_token"]
    assert "token" not in challenge

    # A purpose-scoped challenge must never authenticate normal API calls.
    assert client.get(
        "/api/auth/me", headers=auth_headers(challenge["challenge_token"])
    ).status_code == 401
    from app.security.jwt import decode_token

    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(challenge["challenge_token"])

    wrong = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": challenge["challenge_token"], "code": "000000"},
    )
    assert wrong.status_code == 401

    code = _code(secret)
    verified = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": challenge["challenge_token"], "code": code},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["token"]
    assert verified.json()["data"]["user"]["email"] == "mfa@example.com"

    replay = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": challenge["challenge_token"], "code": code},
    )
    assert replay.status_code == 401
    assert "already used" in replay.text.lower()


def test_mfa_disable_restores_password_only_login(client):
    data = register(client, "disable@example.com", PASSWORD)
    token = data["token"]
    secret, _ = _setup_and_enable(client, token)

    login = client.post(
        "/api/auth/login",
        json={"email": "disable@example.com", "password": PASSWORD},
    )
    challenge = login.json()["data"]
    assert challenge["mfa_required"] is True
    verified = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": challenge["challenge_token"], "code": _code(secret)},
    )
    assert verified.status_code == 200, verified.text

    wrong_password = client.post(
        "/api/auth/mfa/disable",
        json={"password": "WrongPassword1!", "code": _code(secret, 1)},
        headers=auth_headers(token),
    )
    assert wrong_password.status_code == 401

    disabled = client.post(
        "/api/auth/mfa/disable",
        json={"password": PASSWORD, "code": _code(secret, 1)},
        headers=auth_headers(token),
    )
    assert disabled.status_code == 200, disabled.text

    after = client.post(
        "/api/auth/login",
        json={"email": "disable@example.com", "password": PASSWORD},
    )
    assert after.status_code == 200
    assert after.json()["data"]["token"]
    assert "mfa_required" not in after.json()["data"]


def test_mfa_requires_current_password_and_active_account(client):
    data = register(client, "inactive-mfa@example.com", PASSWORD)
    token = data["token"]

    no_password = client.post(
        "/api/auth/mfa/setup",
        json={"password": "not-the-password"},
        headers=auth_headers(token),
    )
    assert no_password.status_code == 401

    _setup_and_enable(client, token)
    login = client.post(
        "/api/auth/login",
        json={"email": "inactive-mfa@example.com", "password": PASSWORD},
    )
    challenge = login.json()["data"]

    from app.db import get_session
    from app.models import User

    db = get_session()
    try:
        user = db.get(User, data["user"]["id"])
        assert user is not None
        user.active = False
        db.commit()
    finally:
        db.close()

    verified = client.post(
        "/api/auth/mfa/verify",
        json={"challenge_token": challenge["challenge_token"], "code": "123456"},
    )
    assert verified.status_code == 401


def test_mfa_recovery_codes_are_single_use(client):
    data = register(client, "recovery@example.com", PASSWORD)
    _, recovery_codes = _setup_and_enable(client, data["token"])
    login = client.post(
        "/api/auth/login",
        json={"email": "recovery@example.com", "password": PASSWORD},
    )
    challenge = login.json()["data"]

    verified = client.post(
        "/api/auth/mfa/verify",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": recovery_codes[0],
        },
    )
    assert verified.status_code == 200, verified.text

    replay = client.post(
        "/api/auth/mfa/verify",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": recovery_codes[0],
        },
    )
    assert replay.status_code == 401

    second = client.post(
        "/api/auth/mfa/verify",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": recovery_codes[1],
        },
    )
    assert second.status_code == 200, second.text


def test_mfa_setup_rotates_pending_secret(client):
    data = register(client, "rotate@example.com", PASSWORD)
    headers = auth_headers(data["token"])
    first = client.post(
        "/api/auth/mfa/setup", json={"password": PASSWORD}, headers=headers
    )
    second = client.post(
        "/api/auth/mfa/setup", json={"password": PASSWORD}, headers=headers
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["secret"] != second.json()["data"]["secret"]
    assert client.get("/api/auth/mfa", headers=headers).json()["data"]["enabled"] is False
