"""Organization-wide MFA policy and forced enrollment tests."""

from __future__ import annotations

import time
import uuid

import pytest

from app.security.totp import code_at, current_step
from tests.test_api.conftest import auth_headers, register

PASSWORD = "Password123!"


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    from app.api.auth import login_throttle

    login_throttle.reset()
    yield
    login_throttle.reset()


def _code(secret: str) -> str:
    return code_at(secret, current_step())


def _wrong_code(secret: str) -> str:
    return "111111" if _code(secret) != "111111" else "222222"


def _org_with_mfa_policy(client, require_mfa: bool = True, via_api: bool = False):
    data = register(client, f"org-mfa-{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
    headers = auth_headers(data["token"])
    created = client.post(
        "/api/organizations",
        json={"name": f"MFA Org {uuid.uuid4().hex[:8]}"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    org_id = created.json()["data"]["id"]
    if via_api:
        patched = client.patch(
            f"/api/organizations/{org_id}",
            json={"require_mfa": require_mfa},
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["data"]["require_mfa"] is require_mfa

    from app.db import get_session
    from app.models import Organization, User

    db = get_session()
    try:
        user = db.get(User, data["user"]["id"])
        assert user is not None
        user.organization_id = org_id
        if not via_api:
            org = db.get(Organization, org_id)
            assert org is not None
            org.require_mfa = require_mfa
        db.commit()
    finally:
        db.close()
    return data, headers, org_id


def test_org_policy_forces_enrollment_then_normal_login(client):
    data, headers, org_id = _org_with_mfa_policy(client, True)
    login = client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    required = login.json()["data"]
    assert required["mfa_enrollment_required"] is True
    assert required["enrollment_token"]
    assert "token" not in required

    # The enrollment token is purpose-scoped, never a bearer credential.
    assert client.get(
        "/api/auth/me", headers=auth_headers(required["enrollment_token"])
    ).status_code == 401

    started = client.post(
        "/api/auth/mfa/enroll/start",
        json={"enrollment_token": required["enrollment_token"]},
    )
    assert started.status_code == 200, started.text
    secret = started.json()["data"]["secret"]
    assert started.json()["data"]["otpauth_uri"].startswith("otpauth://totp/")

    wrong = client.post(
        "/api/auth/mfa/enroll/complete",
        json={
            "enrollment_token": required["enrollment_token"],
            "code": _wrong_code(secret),
        },
    )
    assert wrong.status_code == 401

    completed = client.post(
        "/api/auth/mfa/enroll/complete",
        json={"enrollment_token": required["enrollment_token"], "code": _code(secret)},
    )
    assert completed.status_code == 200, completed.text
    result = completed.json()["data"]
    assert result["token"]
    assert result["user"]["email"] == data["user"]["email"]
    assert len(result["recovery_codes"]) == 10

    # MFA is now enabled, so the next login gets the normal challenge.
    again = client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": PASSWORD},
    )
    assert again.status_code == 200
    assert again.json()["data"]["mfa_required"] is True

    # Reusing the completed enrollment token is rejected (not a second login).
    reused = client.post(
        "/api/auth/mfa/enroll/complete",
        json={"enrollment_token": required["enrollment_token"], "code": _code(secret)},
    )
    assert reused.status_code == 409


def test_org_policy_uses_membership_when_primary_org_is_unset(client):
    data, _, _ = _org_with_mfa_policy(client, True)

    from app.db import get_session
    from app.models import User

    db = get_session()
    try:
        user = db.get(User, data["user"]["id"])
        assert user is not None
        user.organization_id = None
        db.commit()
    finally:
        db.close()

    login = client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["data"]["mfa_enrollment_required"] is True


def test_enabling_org_mfa_policy_revokes_existing_tokens(client):
    data, headers, org_id = _org_with_mfa_policy(client, False)
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    # JWT iat has one-second resolution; move past the token's second so the
    # policy cutoff is unambiguously later than the issued token.
    time.sleep(1.05)
    patched = client.patch(
        f"/api/organizations/{org_id}",
        json={"require_mfa": True},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text

    # Existing bearer tokens are stale immediately; renewal must not launder
    # a stale token into a fresh one. The user must log in and complete forced
    # enrollment before receiving a new token.
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post(
        "/api/auth/sessions/renew", headers=headers
    ).status_code == 401
    login = client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["data"]["mfa_enrollment_required"] is True


def test_org_policy_can_be_turned_off_and_policy_is_visible(client):
    data, headers, org_id = _org_with_mfa_policy(client, True)
    listed = client.get("/api/organizations?pageSize=100", headers=headers)
    assert listed.status_code == 200
    org = next(o for o in listed.json()["data"] if o["id"] == org_id)
    assert org["require_mfa"] is True

    patched = client.patch(
        f"/api/organizations/{org_id}",
        json={"require_mfa": False},
        headers=headers,
    )
    assert patched.status_code == 200
    login = client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["data"]["token"]
    assert "mfa_enrollment_required" not in login.json()["data"]


def test_org_policy_blocks_disable_and_reenrolls_when_policy_is_off(client):
    data, _, org_id = _org_with_mfa_policy(client, True)
    first = client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": PASSWORD},
    ).json()["data"]
    started = client.post(
        "/api/auth/mfa/enroll/start",
        json={"enrollment_token": first["enrollment_token"]},
    ).json()["data"]
    secret = started["secret"]
    completed = client.post(
        "/api/auth/mfa/enroll/complete",
        json={"enrollment_token": first["enrollment_token"], "code": _code(secret)},
    )
    assert completed.status_code == 200
    token_headers = auth_headers(completed.json()["data"]["token"])

    blocked = client.post(
        "/api/auth/mfa/disable",
        json={"password": PASSWORD, "code": _code(secret)},
        headers=token_headers,
    )
    assert blocked.status_code == 409

    unset = client.patch(
        f"/api/organizations/{org_id}",
        json={"require_mfa": False},
        headers=token_headers,
    )
    assert unset.status_code == 200

    disabled = client.post(
        "/api/auth/mfa/disable",
        json={"password": PASSWORD, "code": _code(secret)},
        headers=token_headers,
    )
    assert disabled.status_code == 200, disabled.text

    # Re-enable the policy directly (the user now has no MFA) and verify the
    # next login is forced back into enrollment.
    from app.db import get_session
    from app.models import Organization

    db = get_session()
    try:
        org = db.get(Organization, org_id)
        assert org is not None
        org.require_mfa = True
        db.commit()
    finally:
        db.close()

    again = client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": PASSWORD},
    )
    assert again.status_code == 200
    assert again.json()["data"]["mfa_enrollment_required"] is True


def test_only_founder_can_change_org_mfa_policy(client):
    data, _, org_id = _org_with_mfa_policy(client, False)
    other = register(client, f"other-{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
    denied = client.patch(
        f"/api/organizations/{org_id}",
        json={"require_mfa": True},
        headers=auth_headers(other["token"]),
    )
    assert denied.status_code == 403

    from app.db import get_session
    from app.models import Organization

    db = get_session()
    try:
        org = db.get(Organization, org_id)
        assert org is not None
        assert org.require_mfa is False
    finally:
        db.close()


def test_deactivated_user_cannot_start_forced_enrollment(client):
    data, _, _ = _org_with_mfa_policy(client, True)
    required = client.post(
        "/api/auth/login",
        json={"email": data["user"]["email"], "password": PASSWORD},
    ).json()["data"]

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

    started = client.post(
        "/api/auth/mfa/enroll/start",
        json={"enrollment_token": required["enrollment_token"]},
    )
    assert started.status_code == 401
