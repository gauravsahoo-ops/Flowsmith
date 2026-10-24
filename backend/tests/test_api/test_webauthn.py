"""WebAuthn/passkey registration, login, replay, and configuration tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os

import cbor2
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import get_settings
from tests.test_api.conftest import auth_headers, register

PASSWORD = "Password123!"
RP_ID = "example.com"
ORIGIN = "https://example.com"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _auth_data(*, flags: int, sign_count: int, attested: bytes = b"") -> bytes:
    return (
        hashlib.sha256(RP_ID.encode()).digest()
        + bytes([flags])
        + sign_count.to_bytes(4, "big")
        + attested
    )


def _registration_credential(challenge: str):
    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    credential_id = os.urandom(16)
    cose_key = cbor2.dumps({
        1: 2,
        3: -7,
        -1: 1,
        -2: numbers.x.to_bytes(32, "big"),
        -3: numbers.y.to_bytes(32, "big"),
    })
    attested = (
        b"\x00" * 16
        + len(credential_id).to_bytes(2, "big")
        + credential_id
        + cose_key
    )
    auth_data = _auth_data(flags=0x45, sign_count=0, attested=attested)
    client_data = json.dumps({
        "type": "webauthn.create",
        "challenge": challenge,
        "origin": ORIGIN,
        "crossOrigin": False,
    }, separators=(",", ":")).encode()
    attestation = cbor2.dumps({
        "fmt": "none",
        "attStmt": {},
        "authData": auth_data,
    })
    credential = {
        "id": _b64(credential_id),
        "rawId": _b64(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": _b64(client_data),
            "attestationObject": _b64(attestation),
            "transports": ["internal"],
        },
        "clientExtensionResults": {},
    }
    return key, credential_id, credential


def _assertion(challenge: str, key, credential_id: bytes, *, sign_count: int = 1):
    auth_data = _auth_data(flags=0x05, sign_count=sign_count)
    client_data = json.dumps({
        "type": "webauthn.get",
        "challenge": challenge,
        "origin": ORIGIN,
        "crossOrigin": False,
    }, separators=(",", ":")).encode()
    signature = key.sign(
        auth_data + hashlib.sha256(client_data).digest(),
        ec.ECDSA(hashes.SHA256()),
    )
    return {
        "id": _b64(credential_id),
        "rawId": _b64(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": _b64(client_data),
            "authenticatorData": _b64(auth_data),
            "signature": _b64(signature),
            "userHandle": None,
        },
        "clientExtensionResults": {},
    }


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    from app.api.auth import login_throttle

    login_throttle.reset()
    yield
    login_throttle.reset()


@pytest.fixture
def webauthn_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "webauthn_enabled", True, raising=False)
    monkeypatch.setattr(settings, "webauthn_rp_id", RP_ID, raising=False)
    monkeypatch.setattr(settings, "webauthn_rp_name", "Flowsmith Test", raising=False)
    monkeypatch.setattr(settings, "webauthn_origin", ORIGIN, raising=False)
    monkeypatch.setattr(settings, "webauthn_require_uv", True, raising=False)
    return settings


def _register_passkey(client, headers):
    options_response = client.post(
        "/api/auth/webauthn/register/options",
        json={"password": PASSWORD},
        headers=headers,
    )
    assert options_response.status_code == 200, options_response.text
    options = options_response.json()["data"]
    key, credential_id, credential = _registration_credential(
        options["options"]["challenge"]
    )
    completed = client.post(
        "/api/auth/webauthn/register/complete",
        json={
            "registration_token": options["registration_token"],
            "credential": credential,
            "name": "Test Passkey",
        },
    )
    assert completed.status_code == 200, completed.text
    return options, key, credential_id


def test_passkey_registration_and_login(client, webauthn_settings):
    data = register(client, "passkey@example.com", PASSWORD)
    headers = auth_headers(data["token"])
    options, key, credential_id = _register_passkey(client, headers)

    status = client.get("/api/auth/webauthn", headers=headers)
    assert status.status_code == 200
    assert status.json()["data"]["enabled"] is True
    assert status.json()["data"]["credentials"][0]["name"] == "Test Passkey"

    login = client.post(
        "/api/auth/login",
        json={"email": "passkey@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    challenge = login.json()["data"]
    assert challenge["webauthn_required"] is True
    assert challenge.get("mfa_required") is not True
    assert challenge["webauthn_token"]
    assert "token" not in challenge

    # Challenge tokens are purpose-scoped, never bearer credentials.
    assert client.get(
        "/api/auth/me", headers=auth_headers(challenge["webauthn_token"])
    ).status_code == 401
    from app.security.jwt import decode_token

    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(challenge["webauthn_token"])

    assertion = _assertion(
        challenge["webauthn_options"]["challenge"], key, credential_id, sign_count=1
    )
    authenticated = client.post(
        "/api/auth/webauthn/authenticate/complete",
        json={
            "webauthn_token": challenge["webauthn_token"],
            "credential": assertion,
        },
    )
    assert authenticated.status_code == 200, authenticated.text
    assert authenticated.json()["data"]["token"]
    assert authenticated.json()["data"]["user"]["email"] == "passkey@example.com"

    replay = client.post(
        "/api/auth/webauthn/authenticate/complete",
        json={
            "webauthn_token": challenge["webauthn_token"],
            "credential": assertion,
        },
    )
    assert replay.status_code == 401

    # A registration challenge cannot be replayed either.
    reused_registration = client.post(
        "/api/auth/webauthn/register/complete",
        json={
            "registration_token": options["registration_token"],
            "credential": _registration_credential(
                options["options"]["challenge"]
            )[2],
        },
    )
    assert reused_registration.status_code == 401


def test_passkey_requires_current_password_for_registration(client, webauthn_settings):
    data = register(client, "passkey-password@example.com", PASSWORD)
    response = client.post(
        "/api/auth/webauthn/register/options",
        json={"password": "WrongPassword1!"},
        headers=auth_headers(data["token"]),
    )
    assert response.status_code == 401


def test_passkey_registration_disabled_without_configuration(client):
    data = register(client, "passkey-disabled@example.com", PASSWORD)
    response = client.post(
        "/api/auth/webauthn/register/options",
        json={"password": PASSWORD},
        headers=auth_headers(data["token"]),
    )
    assert response.status_code == 400
    status = client.get(
        "/api/auth/webauthn", headers=auth_headers(data["token"])
    )
    assert status.status_code == 200
    assert status.json()["data"]["enabled"] is False


def test_webauthn_attestation_policy(monkeypatch):
    from types import SimpleNamespace

    from app.services.webauthn import WebAuthnPolicyError, enforce_attestation_policy

    settings = get_settings()
    monkeypatch.setattr(settings, "webauthn_attestation", "none", raising=False)
    enforce_attestation_policy(SimpleNamespace(fmt=SimpleNamespace(value="none"), aaguid=""))

    monkeypatch.setattr(settings, "webauthn_attestation", "direct", raising=False)
    monkeypatch.setattr(settings, "webauthn_allowed_formats", "", raising=False)
    monkeypatch.setattr(settings, "webauthn_allowed_aaguids", "", raising=False)
    with pytest.raises(WebAuthnPolicyError, match="required"):
        enforce_attestation_policy(SimpleNamespace(fmt=SimpleNamespace(value="none"), aaguid=""))

    monkeypatch.setattr(settings, "webauthn_allowed_formats", "packed", raising=False)
    monkeypatch.setattr(
        settings, "webauthn_allowed_aaguids",
        "11111111-1111-1111-1111-111111111111", raising=False,
    )
    enforce_attestation_policy(SimpleNamespace(
        fmt=SimpleNamespace(value="packed"),
        aaguid="11111111-1111-1111-1111-111111111111",
    ))
    with pytest.raises(WebAuthnPolicyError, match="AAGUID"):
        enforce_attestation_policy(SimpleNamespace(
            fmt=SimpleNamespace(value="packed"),
            aaguid="22222222-2222-2222-2222-222222222222",
        ))
    with pytest.raises(WebAuthnPolicyError, match="format"):
        enforce_attestation_policy(SimpleNamespace(
            fmt=SimpleNamespace(value="tpm"),
            aaguid="11111111-1111-1111-1111-111111111111",
        ))


def test_conditional_passkey_login_is_passwordless_and_single_use(client, webauthn_settings):
    data = register(client, "conditional@example.com", PASSWORD)
    _, key, credential_id = _register_passkey(client, auth_headers(data["token"]))

    options_response = client.post("/api/auth/webauthn/conditional/options")
    assert options_response.status_code == 200, options_response.text
    options = options_response.json()["data"]
    assert options["options"]["allowCredentials"] == []
    assertion = _assertion(
        options["options"]["challenge"], key, credential_id, sign_count=1
    )
    completed = client.post(
        "/api/auth/webauthn/conditional/complete",
        json={
            "webauthn_token": options["webauthn_token"],
            "credential": assertion,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["token"]
    assert completed.json()["data"]["user"]["email"] == "conditional@example.com"

    replay = client.post(
        "/api/auth/webauthn/conditional/complete",
        json={
            "webauthn_token": options["webauthn_token"],
            "credential": assertion,
        },
    )
    assert replay.status_code == 401


def test_conditional_passkey_rejects_unknown_credential(client, webauthn_settings):
    _, _, credential = _registration_credential("unused")
    response = client.post(
        "/api/auth/webauthn/conditional/options"
    ).json()["data"]
    unknown = client.post(
        "/api/auth/webauthn/conditional/complete",
        json={
            "webauthn_token": response["webauthn_token"],
            "credential": credential,
        },
    )
    assert unknown.status_code == 401


def test_conditional_passkey_is_unavailable_when_disabled(client):
    response = client.post("/api/auth/webauthn/conditional/options")
    assert response.status_code == 400


def test_passkey_and_totp_are_both_offered(client, webauthn_settings):
    from app.security.totp import code_at, current_step

    data = register(client, "passkey-totp@example.com", PASSWORD)
    headers = auth_headers(data["token"])
    setup = client.post(
        "/api/auth/mfa/setup", json={"password": PASSWORD}, headers=headers
    )
    assert setup.status_code == 200
    secret = setup.json()["data"]["secret"]
    enabled = client.post(
        "/api/auth/mfa/enable",
        json={"password": PASSWORD, "code": code_at(secret, current_step())},
        headers=headers,
    )
    assert enabled.status_code == 200
    _register_passkey(client, headers)

    login = client.post(
        "/api/auth/login",
        json={"email": "passkey-totp@example.com", "password": PASSWORD},
    )
    challenge = login.json()["data"]
    assert challenge["mfa_required"] is True
    assert challenge["webauthn_required"] is True
    assert challenge["challenge_token"] and challenge["webauthn_token"]

    # The TOTP fallback remains usable when both factors are registered.
    totp = client.post(
        "/api/auth/mfa/verify",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": code_at(secret, current_step() + 1),
        },
    )
    assert totp.status_code == 200, totp.text


def test_passkey_satisfies_organization_mfa_policy(client, webauthn_settings):
    data = register(client, "passkey-policy@example.com", PASSWORD)
    headers = auth_headers(data["token"])
    _register_passkey(client, headers)

    from app.db import get_session
    from app.models import Organization, OrganizationMember, User

    db = get_session()
    try:
        user = db.get(User, data["user"]["id"])
        assert user is not None
        org = Organization(
            id="org_passkey_policy", name="Passkey Policy Org",
            founder_id=user.id, require_mfa=True,
        )
        db.add(org)
        db.add(OrganizationMember(
            organization_id=org.id, user_id=user.id, role="admin", permission="admin",
        ))
        user.organization_id = org.id
        db.commit()
    finally:
        db.close()

    login = client.post(
        "/api/auth/login",
        json={"email": "passkey-policy@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200
    challenge = login.json()["data"]
    assert challenge["webauthn_required"] is True
    assert "mfa_enrollment_required" not in challenge


def test_passkey_can_be_deleted(client, webauthn_settings):
    data = register(client, "passkey-delete@example.com", PASSWORD)
    headers = auth_headers(data["token"])
    _, _, credential_id = _register_passkey(client, headers)
    credential_b64 = _b64(credential_id)
    removed = client.delete(
        f"/api/auth/webauthn/{credential_b64}", headers=headers
    )
    assert removed.status_code == 200, removed.text
    status = client.get("/api/auth/webauthn", headers=headers)
    assert status.json()["data"]["credentials"] == []
