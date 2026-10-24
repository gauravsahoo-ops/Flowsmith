"""RFC 6238 TOTP helpers (stdlib only).

The authenticator secret is generated locally, shown once during enrollment,
and stored encrypted by the caller. Codes are six digits with a 30-second
period; verification accepts one period of clock skew in either direction.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD_SECONDS = 30
SECRET_BYTES = 20


def generate_secret() -> str:
    """Return a base32 secret without padding (the format authenticator apps use)."""
    return base64.b32encode(os.urandom(SECRET_BYTES)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    normalized = "".join(secret.split()).upper()
    padding = "=" * (-len(normalized) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def current_step(at_time: float | None = None) -> int:
    return int((time.time() if at_time is None else at_time) // PERIOD_SECONDS)


def code_at(secret: str, step: int, *, digits: int = DIGITS) -> str:
    """Return the TOTP code for an explicit counter value."""
    digest = hmac.new(
        _decode_secret(secret),
        struct.pack(">Q", step),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def verify_code(
    secret: str,
    code: str,
    *,
    at_time: float | None = None,
    window: int = 1,
) -> int | None:
    """Verify a code and return its matched counter, or None.

    Returning the counter lets callers persist the last accepted step and
    reject replay of the same code. A window of one accepts the previous
    and next 30-second step for modest device clock skew.
    """
    normalized = "".join(code.split())
    if not normalized.isdigit() or len(normalized) != DIGITS:
        return None
    step = current_step(at_time)
    for offset in range(-window, window + 1):
        candidate_step = step + offset
        if hmac.compare_digest(code_at(secret, candidate_step), normalized):
            return candidate_step
    return None


def provisioning_uri(secret: str, email: str, issuer: str = "Flowsmith") -> str:
    """Build an otpauth:// URI suitable for authenticator apps."""
    label = quote(f"{issuer}:{email}", safe="")
    query = urlencode({
        "secret": secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": DIGITS,
        "period": PERIOD_SECONDS,
    })
    return f"otpauth://totp/{label}?{query}"
