"""Crypto tools node.

Stdlib hashing and encoding helpers: SHA/MD5 digests, HMAC signatures,
Base64 encode/decode, random token/UUID generation, JWT signing and
verification, and RFC 6238 TOTP codes. No keys are logged; secrets stay in
the credential vault.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

# TOTP defaults from RFC 6238: 6 digits, 30 second step, SHA-1.
TOTP_DEFAULT_DIGITS = 6
TOTP_DEFAULT_STEP = 30


class CryptoToolsParams(BaseModel):
    operation: Literal[
        "hash", "hmac", "base64_encode", "base64_decode", "uuid", "token",
        "jwt_sign", "jwt_verify", "totp_generate", "totp_verify",
    ] = Field(
        default="hash"
    )
    text: str = Field(default="", description="Input text (empty = first input item text).")
    algorithm: str = Field(default="sha256", description="md5 | sha1 | sha256 | sha512.")
    key: str = Field(default="", description="HMAC secret (prefer {{ $cred.* }} reference).")
    num_bytes: int = Field(default=16, ge=4, le=64, description="Random token bytes.")

    # JWT
    secret: str = Field(default="", description="HMAC secret for HS* signing (jwt_sign).")
    claims: dict[str, Any] = Field(default_factory=dict, description="Claims to encode (jwt_sign).")
    jwt_token: str = Field(default="", description="Token to verify (jwt_verify / totp_verify).")
    issuer: str = Field(default="", description="Expected iss; verification fails on mismatch.")
    audience: str = Field(default="", description="Expected aud; verification fails on mismatch.")
    leeway_seconds: int = Field(default=0, ge=0, le=300, description="Clock-skew tolerance for exp/nbf.")

    # TOTP
    totp_secret: str = Field(default="", description="Base32 TOTP shared secret (prefer {{ $cred.* }}).")
    totp_digits: int = Field(default=TOTP_DEFAULT_DIGITS, ge=6, le=8, description="Code length.")
    totp_step: int = Field(default=TOTP_DEFAULT_STEP, ge=1, le=300, description="Time step in seconds.")
    totp_counter: int = Field(default=0, ge=0, description="Unix time to encode; 0 = now.")


def _source(params: CryptoToolsParams, items: list[dict[str, Any]]) -> str:
    if params.text:
        return params.text
    if not items:
        return ""
    first = items[0] if isinstance(items[0], dict) else {}
    for key in ("text", "value", "data", "content"):
        if isinstance(first.get(key), str):
            return first[key]
    return str(first)


def _hasher(name: str):
    try:
        return hashlib.new(name.lower())
    except Exception as exc:
        raise NodeExecutionError(
            f"Unsupported algorithm {name!r}. Use md5/sha1/sha256/sha512.",
            code="CRYPTO_ALGO_ERROR",
            node_id="crypto_tools",
            retryable=False,
        ) from exc


# The HS* family is the only JWT algorithm FlowSmith signs with. "none" and the
# asymmetric families are deliberately absent: "none" is universally rejected by
# verifiers and the public-key path needs key material the vault does not model
# yet. Verification additionally pins the expected algorithms in PyJWT options
# so a token cannot switch itself to a weaker one (CVE-2022-29217).
_JWT_ALLOWED = ("HS256", "HS384", "HS512")


def _jwt_alg(params: CryptoToolsParams) -> str:
    """Map the node's algorithm field onto a JWT HS* alg identifier."""
    name = (params.algorithm or "sha256").upper().replace("SHA-", "HS").replace("SHA", "HS")
    alg = name if name in _JWT_ALLOWED else "HS256"
    return alg


def _require_secret(value: str, what: str) -> str:
    secret = str(value or "").strip()
    if not secret:
        raise NodeExecutionError(
            f"{what} requires a secret. Reference one from the credential vault.",
            code="CRYPTO_KEY_MISSING",
            node_id="crypto_tools",
            retryable=False,
        )
    return secret


def _pyjwt():
    """Import PyJWT on demand.

    Loaded lazily so a deployment without it still registers the node and its
    hashing/TOTP operations; only the JWT operations then report the gap.
    """
    try:
        import jwt as _jwt
    except ImportError as exc:  # pragma: no cover - depends on deployment
        raise NodeExecutionError(
            "JWT operations require the PyJWT package (pip install PyJWT).",
            code="CRYPTO_JWT_UNAVAILABLE",
            node_id="crypto_tools",
            retryable=False,
        ) from exc
    return _jwt


def _b32_decode(secret: str) -> bytes:
    """Decode a base32 shared secret, tolerating padding and spacing."""
    cleaned = secret.replace(" ", "").replace("-", "").upper()
    padded = cleaned + "=" * ((8 - len(cleaned) % 8) % 8)
    try:
        return base64.b32decode(padded)
    except Exception as exc:
        raise NodeExecutionError(
            "TOTP secret must be base32 (A-Z, 2-7).",
            code="CRYPTO_TOTP_SECRET",
            node_id="crypto_tools",
            retryable=False,
        ) from exc


def _hotp(key: bytes, counter: int, digits: int, algorithm: str) -> str:
    """RFC 4226 HOTP. TOTP is HOTP over a time counter (RFC 6238)."""
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, algorithm).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


@register
class CryptoToolsNode(BaseNode[CryptoToolsParams]):
    node_type = "crypto_tools"
    display_name = "Crypto"
    version = 1
    description = "Hash, HMAC, Base64, UUID, and secure tokens."
    category = "Transform"
    icon = "crypto_tools"
    parameters_schema = CryptoToolsParams

    # Declared so the config panel hides fields that do not apply to the
    # selected operation. `text` and `algorithm` are shared by the digest
    # operations; TOTP reads its own secret and never the digest fields.
    operations: dict[str, dict[str, Any]] = {
        "hash": {
            "display_name": "Hash",
            "description": "Hash the input text with a digest algorithm.",
            "properties": ["text", "algorithm"],
            "required": [],
            "idempotency": "idempotent",
            "retryable": True,
        },
        "hmac": {
            "display_name": "HMAC",
            "description": "Keyed-hash message authentication code.",
            "properties": ["text", "algorithm", "key"],
            "required": ["key"],
            "idempotency": "idempotent",
            "retryable": True,
        },
        "base64_encode": {
            "display_name": "Base64 Encode",
            "description": "Encode the input text as Base64.",
            "properties": ["text"],
            "required": [],
            "idempotency": "idempotent",
            "retryable": True,
        },
        "base64_decode": {
            "display_name": "Base64 Decode",
            "description": "Decode Base64 text back to a UTF-8 string.",
            "properties": ["text"],
            "required": [],
            "idempotency": "idempotent",
            "retryable": True,
        },
        "uuid": {
            "display_name": "UUID",
            "description": "Generate a random version 4 UUID.",
            "properties": [],
            "required": [],
            "idempotency": "non_idempotent",
            "retryable": False,
        },
        "token": {
            "display_name": "Secure Token",
            "description": "Generate a URL-safe random token.",
            "properties": ["num_bytes"],
            "required": [],
            "idempotency": "non_idempotent",
            "retryable": False,
        },
        "jwt_sign": {
            "display_name": "Sign JWT",
            "description": "Sign claims into a compact HS* JWT.",
            "properties": ["secret", "claims", "algorithm"],
            "required": ["secret"],
            "idempotency": "idempotent",
            "retryable": True,
        },
        "jwt_verify": {
            "display_name": "Verify JWT",
            "description": "Verify a JWT and return its claims, or why it failed.",
            "properties": ["jwt_token", "secret", "issuer", "audience", "leeway_seconds"],
            "required": ["jwt_token", "secret"],
            "idempotency": "idempotent",
            "retryable": True,
        },
        "totp_generate": {
            "display_name": "Generate TOTP",
            "description": "Generate an RFC 6238 time-based one-time password.",
            "properties": ["totp_secret", "totp_digits", "totp_step", "totp_counter"],
            "required": ["totp_secret"],
            "idempotency": "conditionally_idempotent",
            "retryable": False,
        },
        "totp_verify": {
            "display_name": "Verify TOTP",
            "description": "Check a code against the current and neighbouring windows.",
            "properties": ["jwt_token", "totp_secret", "totp_digits", "totp_step", "totp_counter"],
            "required": ["jwt_token", "totp_secret"],
            "idempotency": "idempotent",
            "retryable": True,
        },
    }

    async def run(
        self,
        ctx: NodeContext,
        params: CryptoToolsParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if params.operation == "uuid":
            return NodeResult(output_items=[{"uuid": str(uuid.uuid4())}])
        if params.operation == "token":
            return NodeResult(output_items=[{"token": secrets.token_urlsafe(params.num_bytes)}])
        if params.operation == "jwt_sign":
            return self._jwt_sign(params)
        if params.operation == "jwt_verify":
            return self._jwt_verify(params)
        if params.operation == "totp_generate":
            return self._totp_generate(params)
        if params.operation == "totp_verify":
            return self._totp_verify(params)
        src = _source(params, input_items or [])
        if params.operation == "base64_encode":
            return NodeResult(output_items=[{"base64": base64.b64encode(src.encode()).decode()}])
        if params.operation == "base64_decode":
            try:
                return NodeResult(output_items=[{"text": base64.b64decode(src.strip()).decode()}])
            except Exception as exc:
                raise NodeExecutionError(
                    "Invalid Base64 input.",
                    code="CRYPTO_BASE64_ERROR",
                    node_id="crypto_tools",
                    retryable=False,
                ) from exc
        if params.operation == "hmac":
            if not params.key:
                raise NodeExecutionError(
                    "HMAC needs a key (use a credential reference).",
                    code="CRYPTO_KEY_MISSING",
                    node_id="crypto_tools",
                    retryable=False,
                )
            digest = hmac.new(params.key.encode(), src.encode(), params.algorithm.lower()).hexdigest()
            return NodeResult(output_items=[{"hmac": digest, "algorithm": params.algorithm}])
        h = _hasher(params.algorithm)
        h.update(src.encode())
        return NodeResult(output_items=[{"digest": h.hexdigest(), "algorithm": params.algorithm}])

    # ------------------------------------------------------------------
    # JWT (HS*)
    # ------------------------------------------------------------------

    def _jwt_sign(self, params: CryptoToolsParams) -> NodeResult:
        jwt = _pyjwt()
        secret = _require_secret(params.secret, "jwt_sign")
        alg = _jwt_alg(params)
        claims = dict(params.claims or {})
        try:
            token = jwt.encode(claims, secret, algorithm=alg)
        except Exception as exc:
            raise NodeExecutionError(
                f"Could not sign JWT: {exc}",
                code="CRYPTO_JWT_ERROR",
                node_id="crypto_tools",
                retryable=False,
            ) from exc
        return NodeResult(output_items=[{
            "token": token,
            "algorithm": alg,
            "claims": claims,
        }])

    def _jwt_verify(self, params: CryptoToolsParams) -> NodeResult:
        jwt = _pyjwt()
        token = str(params.jwt_token or params.text or "").strip()
        if not token:
            raise NodeExecutionError(
                "jwt_verify needs a token to check.",
                code="CRYPTO_JWT_MISSING_TOKEN",
                node_id="crypto_tools",
                retryable=False,
            )
        secret = _require_secret(params.secret, "jwt_verify")

        # No claim is force-required. PyJWT already validates `exp`, `iss` and
        # `aud` when they are present or an expectation is given; `require` only
        # forces them to be *present*, which would wrongly reject plain tokens
        # and would make an expired one look malformed instead of expired.
        # Algorithms are pinned unconditionally, and that is the check which
        # actually has to be unconditional.
        options: dict[str, Any] = {"require": []}

        try:
            # Pinning `algorithms` is what blocks algorithm confusion: a token
            # declaring "none" or an asymmetric alg is rejected before its
            # claims are ever read.
            claims = jwt.decode(
                token,
                secret,
                algorithms=list(_JWT_ALLOWED),
                options=options,
                issuer=params.issuer or None,
                audience=params.audience or None,
                leeway=params.leeway_seconds,
            )
        except jwt.ExpiredSignatureError as exc:
            # Expired is reported as a value, not an error: a caller deciding
            # whether to refresh a token needs the outcome, not an exception.
            return NodeResult(output_items=[{
                "valid": False,
                "reason": "expired",
                "error": str(exc),
            }])
        except jwt.InvalidTokenError as exc:
            return NodeResult(output_items=[{
                "valid": False,
                "reason": "invalid",
                "error": str(exc),
            }])

        return NodeResult(output_items=[{"valid": True, "claims": claims}])

    # ------------------------------------------------------------------
    # TOTP (RFC 6238)
    # ------------------------------------------------------------------

    def _totp(self, params: CryptoToolsParams) -> tuple[str, int]:
        secret = _require_secret(params.totp_secret, "TOTP")
        key = _b32_decode(secret)
        step = params.totp_step or TOTP_DEFAULT_STEP
        digits = params.totp_digits or TOTP_DEFAULT_DIGITS
        counter = params.totp_counter or int(time.time())
        current = counter // step
        # RFC 6238 defines TOTP on top of HOTP with SHA-1 as the reference
        # digest; that is what authenticator apps implement and what the RFC's
        # test vectors pin. SHA-256/512 exist but need issuer coordination, so
        # they are not silently selectable here.
        return _hotp(key, current, digits, "sha1"), current

    def _totp_generate(self, params: CryptoToolsParams) -> NodeResult:
        code, counter = self._totp(params)
        step = params.totp_step or TOTP_DEFAULT_STEP
        now = params.totp_counter or int(time.time())
        return NodeResult(output_items=[{
            "code": code,
            "counter": counter,
            "remaining_seconds": max(0, step - (now % step)),
            "digits": params.totp_digits or TOTP_DEFAULT_DIGITS,
            "step": step,
        }])

    def _totp_verify(self, params: CryptoToolsParams) -> NodeResult:
        presented = str(params.jwt_token or params.text or "").strip()
        if not presented:
            raise NodeExecutionError(
                "totp_verify needs a code to check.",
                code="CRYPTO_TOTP_MISSING_CODE",
                node_id="crypto_tools",
                retryable=False,
            )
        expected, counter = self._totp(params)
        # Compare against the neighbouring windows too, which is what real
        # verifiers do to absorb transmission and clock drift.
        match = presented == expected
        window = 1 if not match else 0
        if not match:
            key = _b32_decode(_require_secret(params.totp_secret, "TOTP"))
            step = params.totp_step or TOTP_DEFAULT_STEP
            digits = params.totp_digits or TOTP_DEFAULT_DIGITS
            for delta in (-1, 1):
                if hmac.compare_digest(expected, _hotp(key, counter + delta, digits, "sha1")):
                    window = delta
                    match = True
                    break
                if hmac.compare_digest(presented, _hotp(key, counter + delta, digits, "sha1")):
                    window = delta
                    match = True
                    break
        return NodeResult(output_items=[{
            "valid": match,
            "window_offset": window if match else None,
            "expected": expected if match else None,
        }])
