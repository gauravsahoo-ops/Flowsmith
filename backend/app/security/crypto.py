"""Fernet credential encryption (spec 12.1, non-negotiable).

Credential data is AES-128-CBC encrypted at rest with a key from the
`CREDENTIALS_ENCRYPTION_KEY` environment variable. For development the
key is derived from `jwt_secret` when the env var is absent (stable
across restarts); production must set the env var (spec 29.1) and back
it up --- losing the key means losing all credentials.

Key rotation: the variable accepts a comma-separated list; the FIRST
key encrypts new data, and every stored token carries a `k{idx}:`
prefix so old values stay decryptable while keys are rolled. To rotate,
prepend the new key, re-encrypt stored credentials (app.credentials),
then remove the old key from the variable.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger("crypto")

PREFIX_RE = re.compile(r"^k(\d+):")


class CredentialDecryptionError(Exception):
    """Ciphertext could not be decrypted (wrong key / corrupted blob)."""


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


def encrypt_text(plaintext: str) -> bytes:
    """Encrypt JSON text; returns a Fernet token prefixed with the key
    index used (`k0:...`)."""
    token = Fernet(_current_key()).encrypt(plaintext.encode())
    return f"k0:{token.decode()}".encode()


def _try_keys(token: bytes, candidate: list[bytes]) -> str:
    for key in candidate:
        try:
            return Fernet(key).decrypt(token).decode()
        except (InvalidToken, ValueError):
            continue
    raise CredentialDecryptionError(
        "Credential could not be decrypted (encryption key changed or data corrupted)."
    )


def decrypt_text(stored: bytes) -> str:
    """Decrypt a stored token back to JSON text. Honours the `k{idx}:`
    prefix when present; legacy un-prefixed tokens fall back to trying
    every configured key (in order)."""
    text = stored.decode("utf-8", errors="replace")
    match = PREFIX_RE.match(text)
    if match:
        idx = int(match.group(1))
        keys = _keys()
        candidates = []
        if idx < len(keys):
            candidates.append(keys[idx])
        candidates.extend(keys)
        return _try_keys(text[match.end():].encode(), candidates)
    return _try_keys(stored, _keys())
