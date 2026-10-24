"""Ed25519 signing and verification for connector-pack manifests.

The signed payload is the canonical JSON encoding of every manifest field
except ``signature``. ``signing_key_id`` is part of the payload, so a signer
cannot swap key identifiers after signing. Signatures are base64-encoded raw
Ed25519 signatures (64 bytes).

Trusted keys are configured as a JSON object mapping key IDs to either a PEM
public key or a base64-encoded raw 32-byte Ed25519 public key:

    CONNECTOR_PACK_TRUSTED_KEYS={"release-2026":"MCowBQYDK2VwAyEA..."}
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class PackSignatureError(ValueError):
    """Raised when a manifest signature or trusted-key configuration is invalid."""


@dataclass(frozen=True)
class SignatureInfo:
    key_id: str
    sha256: str


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    payload = {key: value for key, value in manifest.items() if key != "signature"}
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PackSignatureError(f"Manifest cannot be canonically encoded: {exc}") from exc


def manifest_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _public_key(value: str) -> Ed25519PublicKey:
    value = value.strip()
    try:
        if value.startswith("-----BEGIN PUBLIC KEY-----"):
            key = serialization.load_pem_public_key(value.encode("utf-8"))
            if not isinstance(key, Ed25519PublicKey):
                raise PackSignatureError("Trusted public key is not Ed25519.")
            return key
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 32:
            raise PackSignatureError("Trusted Ed25519 public key must be 32 bytes.")
        return Ed25519PublicKey.from_public_bytes(raw)
    except PackSignatureError:
        raise
    except Exception as exc:
        raise PackSignatureError(f"Invalid trusted public key: {exc}") from exc


def parse_trusted_keys(raw: str) -> dict[str, Ed25519PublicKey]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PackSignatureError("CONNECTOR_PACK_TRUSTED_KEYS is not valid JSON.") from exc
    if not isinstance(data, dict) or not data:
        raise PackSignatureError("CONNECTOR_PACK_TRUSTED_KEYS must be a non-empty JSON object.")
    keys: dict[str, Ed25519PublicKey] = {}
    for key_id, value in data.items():
        if not isinstance(key_id, str) or not key_id.strip():
            raise PackSignatureError("Trusted key IDs must be non-empty strings.")
        if not isinstance(value, str) or not value.strip():
            raise PackSignatureError(f"Trusted key '{key_id}' must be a non-empty string.")
        keys[key_id.strip()] = _public_key(value)
    return keys


def sign_manifest(
    manifest: dict[str, Any],
    private_key: Ed25519PrivateKey,
    key_id: str,
) -> dict[str, Any]:
    if not key_id.strip():
        raise PackSignatureError("A non-empty signing key ID is required.")
    signed = dict(manifest)
    signed["signing_key_id"] = key_id.strip()
    signature = private_key.sign(canonical_manifest_bytes(signed))
    signed["signature"] = base64.b64encode(signature).decode("ascii")
    return signed


def verify_manifest_signature(
    manifest: dict[str, Any],
    trusted_keys: dict[str, Ed25519PublicKey],
    revoked_key_ids: set[str] | frozenset[str] = frozenset(),
) -> SignatureInfo:
    key_id = manifest.get("signing_key_id")
    signature = manifest.get("signature")
    if not isinstance(key_id, str) or not key_id.strip():
        raise PackSignatureError("Manifest requires a signing_key_id.")
    if not isinstance(signature, str) or not signature.strip():
        raise PackSignatureError("Manifest requires a signature.")
    if key_id.strip() in revoked_key_ids:
        raise PackSignatureError(f"Signing key '{key_id}' is revoked.")
    key = trusted_keys.get(key_id.strip())
    if key is None:
        raise PackSignatureError(f"Signing key '{key_id}' is not trusted.")
    try:
        signature_bytes = base64.b64decode(signature.strip(), validate=True)
    except Exception as exc:
        raise PackSignatureError("Manifest signature is not valid base64.") from exc
    if len(signature_bytes) != 64:
        raise PackSignatureError("Ed25519 manifest signature must be 64 bytes.")
    try:
        key.verify(signature_bytes, canonical_manifest_bytes(manifest))
    except InvalidSignature as exc:
        raise PackSignatureError("Manifest signature verification failed.") from exc
    return SignatureInfo(key_id=key_id.strip(), sha256=manifest_digest(manifest))
