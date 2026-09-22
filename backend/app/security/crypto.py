"""Credential encryption service with multi-key rotation and AES-256-GCM cipher (cipher.encryptV2).

Credential data is encrypted at rest using:
- v1 (Fernet / AES-128-CBC + HMAC-SHA256): Default backwards-compatible token.
- v2 (AES-256-GCM): Authenticated Galois/Counter Mode cipher.

Key rotation: CREDENTIALS_ENCRYPTION_KEY accepts a comma-separated list of keys.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

logger = logging.getLogger("crypto")

PREFIX_RE = re.compile(r"^k(\d+):")


class CredentialDecryptionError(Exception):
    """Ciphertext could not be decrypted (wrong key / corrupted blob / bad auth tag)."""


def _keys() -> list[bytes]:
    env_key = get_settings().credentials_encryption_key or os.environ.get("CREDENTIALS_ENCRYPTION_KEY", "")
    if env_key:
        parts = [p.strip() for p in env_key.split(",") if p.strip()]
        if parts:
            return [p.encode() for p in parts]
    digest = hashlib.sha256(get_settings().jwt_secret.encode()).digest()
    logger.warning(
        "CREDENTIALS_ENCRYPTION_KEY not set; deriving a dev key from jwt_secret. "
        "Set the env var in production."
    )
    return [base64.urlsafe_b64encode(digest)]


def _current_key() -> bytes:
    return _keys()[0]


def _derive_aes_256_key(key_material: bytes) -> bytes:
    """Derive 32 bytes (256 bits) for AES-256-GCM using SHA-256."""
    return hashlib.sha256(key_material).digest()


def encrypt_text(plaintext: str) -> bytes:
    """Encrypt JSON text using Fernet; returns token prefixed with key index (k0:...)."""
    token = Fernet(_current_key()).encrypt(plaintext.encode())
    return f"k0:{token.decode()}".encode()


def cipher_encrypt_v2(plaintext: str) -> bytes:
    """AES-256-GCM authenticated encryption.

    Formats output as: v2:{nonce_b64}:{tag_b64}:{ciphertext_b64}
    """
    key = _derive_aes_256_key(_current_key())
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce standard for GCM
    ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    ciphertext = ct_with_tag[:-16]
    tag = ct_with_tag[-16:]

    iv_b64 = base64.urlsafe_b64encode(nonce).decode()
    tag_b64 = base64.urlsafe_b64encode(tag).decode()
    ct_b64 = base64.urlsafe_b64encode(ciphertext).decode()
    return f"v2:{iv_b64}:{tag_b64}:{ct_b64}".encode()


def cipher_decrypt_v2(stored: bytes | str) -> str:
    """Decrypt an AES-256-GCM v2 token or JSON object with iv/authTag/ciphertext."""
    raw_str = stored.decode("utf-8", errors="replace") if isinstance(stored, bytes) else str(stored)
    raw_str = raw_str.strip()

    iv_bytes: bytes
    tag_bytes: bytes
    ct_bytes: bytes

    if raw_str.startswith("v2:"):
        parts = raw_str.split(":")
        if len(parts) != 4:
            raise CredentialDecryptionError("Invalid v2 cipher token structure.")
        try:
            iv_bytes = base64.urlsafe_b64decode(parts[1])
            tag_bytes = base64.urlsafe_b64decode(parts[2])
            ct_bytes = base64.urlsafe_b64decode(parts[3])
        except Exception as exc:
            raise CredentialDecryptionError(f"Malformed base64 in v2 cipher token: {exc}") from exc
    elif raw_str.startswith("{") and "ciphertext" in raw_str:
        # Direct JSON export format: { "iv": "...", "authTag": "...", "ciphertext": "..." }
        try:
            parsed = json.loads(raw_str)
            iv_bytes = base64.b64decode(parsed.get("iv", ""))
            tag_bytes = base64.b64decode(parsed.get("authTag", ""))
            ct_bytes = base64.b64decode(parsed.get("ciphertext", ""))
        except Exception as exc:
            raise CredentialDecryptionError(f"Invalid v2 json cipher format: {exc}") from exc
    else:
        raise CredentialDecryptionError("Not a recognized v2 cipher format.")

    # Combine ciphertext and tag for cryptography AESGCM.decrypt
    ct_with_tag = ct_bytes + tag_bytes

    # Try all configured keys
    for k in _keys():
        try:
            aes_key = _derive_aes_256_key(k)
            pt = AESGCM(aes_key).decrypt(iv_bytes, ct_with_tag, None)
            return pt.decode("utf-8")
        except (InvalidTag, ValueError):
            continue

    raise CredentialDecryptionError(
        "AES-256-GCM credential could not be decrypted (wrong key or corrupted auth tag)."
    )


def _try_keys(token: bytes, candidate: list[bytes]) -> str:
    for key in candidate:
        try:
            return Fernet(key).decrypt(token).decode()
        except (InvalidToken, ValueError):
            continue
    raise CredentialDecryptionError(
        "Credential could not be decrypted (encryption key changed or data corrupted)."
    )


def decrypt_text(stored: bytes | str) -> str:
    """Decrypt stored ciphertext back to plaintext.

    Automatically detects:
    - v2 tokens (v2:... or JSON cipher) -> AES-256-GCM
    - v1 tokens (k0:... or legacy Fernet) -> Fernet AES-128-CBC
    """
    if isinstance(stored, str):
        stored_bytes = stored.encode()
        text = stored
    else:
        stored_bytes = stored
        text = stored.decode("utf-8", errors="replace")

    # Check for v2 AES-256-GCM
    if text.startswith("v2:") or (text.startswith("{") and "ciphertext" in text):
        return cipher_decrypt_v2(stored_bytes)

    # Check for v1 prefixed Fernet
    match = PREFIX_RE.match(text)
    if match:
        idx = int(match.group(1))
        keys = _keys()
        candidates = []
        if idx < len(keys):
            candidates.append(keys[idx])
        candidates.extend(keys)
        return _try_keys(text[match.end():].encode(), candidates)

    return _try_keys(stored_bytes, _keys())


class CipherService:
    """Cipher service providing unified encryption API (cipher.encryptV2, cipher.decryptV2)."""

    encrypt = staticmethod(encrypt_text)
    decrypt = staticmethod(decrypt_text)
    encryptV2 = staticmethod(cipher_encrypt_v2)
    decryptV2 = staticmethod(cipher_decrypt_v2)


# Singleton export of cipher module
cipher = CipherService()
