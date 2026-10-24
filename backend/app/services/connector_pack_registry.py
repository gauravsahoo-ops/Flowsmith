"""Signed connector-pack registry index parsing and verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.services.connector_pack_signing import (
    PackSignatureError,
    SignatureInfo,
    verify_manifest_signature,
)

MAX_REGISTRY_PACKS = 500
MAX_REGISTRY_LIFETIME = timedelta(days=30)
CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class RegistryPack:
    name: str
    display_name: str
    version: str
    description: str
    category: str
    manifest_url: str
    revoked: bool


@dataclass(frozen=True)
class RegistryIndex:
    name: str
    packages: tuple[RegistryPack, ...]
    signature: SignatureInfo


def _string(entry: dict[str, Any], key: str, *, default: str = "", max_length: int = 255) -> str:
    value = entry.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise PackSignatureError(f"Registry field '{key}' must be a string.")
    value = value.strip()
    if len(value) > max_length:
        raise PackSignatureError(f"Registry field '{key}' is too long.")
    return value


def _manifest_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise PackSignatureError("Registry pack manifest_url must use HTTPS.")
    return value


def _timestamp(payload: dict[str, Any], key: str) -> datetime:
    raw = _string(payload, key, max_length=64)
    if not raw:
        raise PackSignatureError(f"Registry field '{key}' is required.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PackSignatureError(
            f"Registry field '{key}' must be an ISO-8601 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise PackSignatureError(
            f"Registry field '{key}' must include a timezone."
        )
    return parsed.astimezone(UTC)


def verify_registry_index(
    payload: dict[str, Any],
    trusted_keys: dict[str, Ed25519PublicKey],
    revoked_key_ids: set[str] | frozenset[str] = frozenset(),
) -> RegistryIndex:
    if not isinstance(payload, dict):
        raise PackSignatureError("Registry index must be a JSON object.")
    if payload.get("schema_version") != 1:
        raise PackSignatureError("Registry index schema_version must be 1.")
    signature = verify_manifest_signature(payload, trusted_keys, revoked_key_ids)

    issued_at = _timestamp(payload, "issued_at")
    expires_at = _timestamp(payload, "expires_at")
    now = datetime.now(UTC)
    if issued_at > now + CLOCK_SKEW:
        raise PackSignatureError("Registry 'issued_at' is in the future.")
    if expires_at <= issued_at:
        raise PackSignatureError("Registry 'expires_at' must be after 'issued_at'.")
    if expires_at <= now:
        raise PackSignatureError("Registry index has expired.")
    if expires_at - issued_at > MAX_REGISTRY_LIFETIME:
        raise PackSignatureError(
            f"Registry index lifetime may not exceed {MAX_REGISTRY_LIFETIME.days} days."
        )

    name = _string(payload, "name", default="Connector Registry", max_length=255)
    raw_packs = payload.get("packs")
    if not isinstance(raw_packs, list):
        raise PackSignatureError("Registry 'packs' must be a list.")
    if len(raw_packs) > MAX_REGISTRY_PACKS:
        raise PackSignatureError(f"A registry may list at most {MAX_REGISTRY_PACKS} packs.")

    packages: list[RegistryPack] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_packs):
        if not isinstance(raw, dict):
            raise PackSignatureError(f"Registry pack at index {index} must be an object.")
        pack_name = _string(raw, "name", max_length=128)
        version = _string(raw, "version", default="1.0.0", max_length=64)
        if not pack_name:
            raise PackSignatureError(f"Registry pack at index {index} requires a name.")
        key = (pack_name, version)
        if key in seen:
            raise PackSignatureError(f"Registry lists {pack_name} {version} more than once.")
        seen.add(key)
        manifest_url = _manifest_url(_string(raw, "manifest_url", max_length=2048))
        revoked = raw.get("revoked", False)
        if not isinstance(revoked, bool):
            raise PackSignatureError("Registry 'revoked' must be a boolean.")
        packages.append(RegistryPack(
            name=pack_name,
            display_name=_string(raw, "display_name", default=pack_name, max_length=255),
            version=version,
            description=_string(raw, "description", max_length=5000),
            category=_string(raw, "category", default="api", max_length=64),
            manifest_url=manifest_url,
            revoked=revoked,
        ))
    return RegistryIndex(name=name, packages=tuple(packages), signature=signature)
