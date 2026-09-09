"""Crypto tools node.

Stdlib hashing and encoding helpers: SHA/MD5 digests, HMAC signatures,
Base64 encode/decode, and random token/UUID generation. No keys are
logged; secrets stay in the credential vault.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class CryptoToolsParams(BaseModel):
    operation: Literal["hash", "hmac", "base64_encode", "base64_decode", "uuid", "token"] = Field(
        default="hash"
    )
    text: str = Field(default="", description="Input text (empty = first input item text).")
    algorithm: str = Field(default="sha256", description="md5 | sha1 | sha256 | sha512.")
    key: str = Field(default="", description="HMAC secret (prefer {{ $cred.* }} reference).")
    num_bytes: int = Field(default=16, ge=4, le=64, description="Random token bytes.")


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


@register
class CryptoToolsNode(BaseNode[CryptoToolsParams]):
    node_type = "crypto_tools"
    display_name = "Crypto"
    version = 1
    description = "Hash, HMAC, Base64, UUID, and secure tokens."
    category = "Transform"
    icon = "🔑"
    parameters_schema = CryptoToolsParams

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
