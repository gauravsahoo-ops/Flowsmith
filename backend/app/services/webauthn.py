"""WebAuthn/passkey option generation and cryptographic verification."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AttestationFormat,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import get_settings
from app.models import User, WebAuthnCredential


class WebAuthnConfigError(Exception):
    pass


class WebAuthnPolicyError(Exception):
    pass


def _origin() -> str:
    return get_settings().webauthn_origin.strip().rstrip("/")


def _rp_id() -> str:
    return get_settings().webauthn_rp_id.strip()


def require_webauthn_config() -> tuple[str, str, str, bool, int]:
    settings = get_settings()
    if not settings.webauthn_enabled:
        raise WebAuthnConfigError("WebAuthn is not enabled.")
    if not _rp_id() or not _origin():
        raise WebAuthnConfigError("WEBAUTHN_RP_ID and WEBAUTHN_ORIGIN are required.")
    return (
        _rp_id(),
        settings.webauthn_rp_name or "Flowsmith",
        _origin(),
        settings.webauthn_require_uv,
        settings.webauthn_timeout_ms,
    )


def registration_options(
    user: User, credentials: list[WebAuthnCredential]
) -> tuple[dict[str, Any], bytes]:
    rp_id, rp_name, _, require_uv, timeout = require_webauthn_config()
    challenge = os.urandom(32)
    selection = AuthenticatorSelectionCriteria(
        resident_key=ResidentKeyRequirement.PREFERRED,
        user_verification=(
            UserVerificationRequirement.REQUIRED
            if require_uv
            else UserVerificationRequirement.PREFERRED
        ),
    )
    policy = (get_settings().webauthn_attestation or "none").strip().lower()
    attestation = {
        "direct": AttestationConveyancePreference.DIRECT,
        "enterprise": AttestationConveyancePreference.ENTERPRISE,
    }.get(policy, AttestationConveyancePreference.NONE)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_name=user.email,
        user_id=str(user.id).encode("utf-8"),
        user_display_name=user.email,
        challenge=challenge,
        timeout=timeout,
        attestation=attestation,
        authenticator_selection=selection,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=credential.credential_id)
            for credential in credentials
        ],
    )
    return json.loads(options_to_json(options)), challenge


def authentication_options(
    credentials: list[WebAuthnCredential],
) -> tuple[dict[str, Any], bytes]:
    rp_id, _, _, require_uv, timeout = require_webauthn_config()
    challenge = os.urandom(32)
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        timeout=timeout,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=credential.credential_id)
            for credential in credentials
        ],
        user_verification=(
            UserVerificationRequirement.REQUIRED
            if require_uv
            else UserVerificationRequirement.PREFERRED
        ),
    )
    return json.loads(options_to_json(options)), challenge


def _attestation_roots() -> dict[AttestationFormat, list[bytes]] | None:
    path = get_settings().webauthn_attestation_roots_file.strip()
    if not path:
        return None
    data = Path(path).read_bytes()
    return {
        fmt: [data]
        for fmt in AttestationFormat
        if fmt is not AttestationFormat.NONE
    }


def enforce_attestation_policy(verified: Any) -> None:
    settings = get_settings()
    policy = (settings.webauthn_attestation or "none").strip().lower()
    if policy == "none":
        return
    fmt = str(getattr(getattr(verified, "fmt", None), "value", "none")).strip().lower()
    if fmt == "none":
        raise WebAuthnPolicyError("Authenticator attestation is required.")
    allowed_formats = {
        item.strip().lower()
        for item in (settings.webauthn_allowed_formats or "").split(",")
        if item.strip()
    }
    if allowed_formats and fmt not in allowed_formats:
        raise WebAuthnPolicyError("Authenticator attestation format is not allowed.")
    allowed_aaguids = {
        item.strip().lower()
        for item in (settings.webauthn_allowed_aaguids or "").split(",")
        if item.strip()
    }
    aaguid = str(getattr(verified, "aaguid", "") or "").strip().lower()
    if allowed_aaguids and aaguid not in allowed_aaguids:
        raise WebAuthnPolicyError("Authenticator AAGUID is not allowed.")


def verify_registration(
    credential: dict[str, Any], challenge: bytes
) -> Any:
    rp_id, _, origin, require_uv, _ = require_webauthn_config()
    verified = verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_presence=True,
        require_user_verification=require_uv,
        pem_root_certs_bytes_by_fmt=_attestation_roots(),
    )
    enforce_attestation_policy(verified)
    return verified


def verify_authentication(
    credential: dict[str, Any],
    challenge: bytes,
    stored: WebAuthnCredential,
) -> Any:
    rp_id, _, origin, require_uv, _ = require_webauthn_config()
    return verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=stored.public_key,
        credential_current_sign_count=stored.sign_count,
        require_user_verification=require_uv,
    )


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def unb64url(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
