"""Crypto node: JWT (HS*) signing/verification and RFC 6238 TOTP.

The TOTP cases are checked against the published RFC 6238 Appendix B reference
vectors, and the underlying HOTP against RFC 4226 Appendix D, so a change to the
digest or counter arithmetic is caught rather than silently accepted.

The JWT cases pin the security properties that matter: an algorithm-confused
token is rejected, an expired token reports `valid: False` instead of raising,
and a missing secret fails loudly rather than signing with an empty key.
"""

from __future__ import annotations

import time

import pytest

from app.engine.errors import NodeExecutionError
from app.engine.node_base import NodeContext
from app.nodes.crypto_tools import CryptoToolsNode, _b32_decode, _hotp
from app.nodes.registry import NODE_REGISTRY, _load_builtin_nodes

_load_builtin_nodes()

# RFC 6238 Appendix B reference secret: base32 of the ASCII digits 0-9 twice.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def _node() -> CryptoToolsNode:
    return CryptoToolsNode()


def _params(**kwargs):
    return CryptoToolsNode.parameters_schema.model_validate(kwargs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_crypto_node_is_registered_with_the_new_operations():
    assert "crypto_tools" in NODE_REGISTRY
    allowed = CryptoToolsNode.parameters_schema.model_fields["operation"].annotation
    for op in ("jwt_sign", "jwt_verify", "totp_generate", "totp_verify"):
        assert op in allowed.__args__


# ---------------------------------------------------------------------------
# HOTP / TOTP reference vectors
# ---------------------------------------------------------------------------


def test_hotp_matches_rfc4226_appendix_d():
    key = _b32_decode(RFC_SECRET)
    for counter, expected in [
        (0, "755224"), (1, "287082"), (2, "359152"), (3, "969429"), (4, "338314"),
    ]:
        assert _hotp(key, counter, 6, "sha1") == expected


@pytest.mark.parametrize(
    "timestamp,expected",
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
async def test_totp_matches_rfc6238_appendix_b(timestamp, expected):
    """The Appendix B vectors are 8-digit, 30-second, SHA-1 codes."""
    res = await _node().run(
        ctx=None,
        params=_params(
            operation="totp_generate",
            totp_secret=RFC_SECRET,
            totp_digits=8,
            totp_counter=timestamp,
        ),
        input_items=[],
    )
    assert res.output_items[0]["code"] == expected
    assert res.output_items[0]["counter"] == timestamp // 30


async def test_totp_counter_defaults_to_the_current_time():
    before = int(time.time())
    res = await _node().run(
        ctx=None, params=_params(operation="totp_generate", totp_secret=RFC_SECRET), input_items=[]
    )
    item = res.output_items[0]
    # A code of the right shape, over the current 30 second window.
    assert len(item["code"]) == 6
    assert item["counter"] == before // 30
    assert 0 <= item["remaining_seconds"] <= 30


async def test_totp_secret_must_be_base32():
    with pytest.raises(NodeExecutionError) as exc:
        await _node().run(
            ctx=None,
            params=_params(operation="totp_generate", totp_secret="not base32!!"),
            input_items=[],
        )
    assert exc.value.code == "CRYPTO_TOTP_SECRET"


async def test_totp_verify_accepts_the_current_code():
    generated = await _node().run(
        ctx=None,
        params=_params(operation="totp_generate", totp_secret=RFC_SECRET, totp_counter=1234567890),
        input_items=[],
    )
    code = generated.output_items[0]["code"]

    res = await _node().run(
        ctx=None,
        params=_params(
            operation="totp_verify",
            totp_secret=RFC_SECRET,
            jwt_token=code,
            totp_counter=1234567890,
        ),
        input_items=[],
    )
    assert res.output_items[0]["valid"] is True
    assert res.output_items[0]["window_offset"] == 0


async def test_totp_verify_tolerates_one_step_of_drift():
    """Real verifiers accept the neighbouring window for clock skew."""
    generated = await _node().run(
        ctx=None,
        params=_params(operation="totp_generate", totp_secret=RFC_SECRET, totp_counter=1234567890),
        input_items=[],
    )
    code = generated.output_items[0]["code"]

    res = await _node().run(
        ctx=None,
        params=_params(
            operation="totp_verify",
            totp_secret=RFC_SECRET,
            jwt_token=code,
            totp_counter=1234567890 + 30,
        ),
        input_items=[],
    )
    assert res.output_items[0]["valid"] is True
    assert res.output_items[0]["window_offset"] == -1


async def test_totp_verify_rejects_a_wrong_code():
    res = await _node().run(
        ctx=None,
        params=_params(
            operation="totp_verify", totp_secret=RFC_SECRET, jwt_token="000000", totp_counter=1234567890
        ),
        input_items=[],
    )
    assert res.output_items[0]["valid"] is False
    # A rejected code must not leak the expected one.
    assert res.output_items[0]["expected"] is None


async def test_totp_verify_requires_a_code():
    with pytest.raises(NodeExecutionError) as exc:
        await _node().run(
            ctx=None, params=_params(operation="totp_verify", totp_secret=RFC_SECRET), input_items=[]
        )
    assert exc.value.code == "CRYPTO_TOTP_MISSING_CODE"


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


async def test_jwt_sign_then_verify_roundtrip():
    signed = await _node().run(
        ctx=None,
        params=_params(operation="jwt_sign", secret="s3cret", claims={"sub": "user-1", "role": "admin"}),
        input_items=[],
    )
    item = signed.output_items[0]
    assert item["algorithm"] == "HS256"
    assert item["token"].count(".") == 2

    verified = await _node().run(
        ctx=None,
        params=_params(operation="jwt_verify", secret="s3cret", jwt_token=item["token"]),
        input_items=[],
    )
    assert verified.output_items[0]["valid"] is True
    assert verified.output_items[0]["claims"]["sub"] == "user-1"


@pytest.mark.parametrize(
    "alg_field,expected",
    [("sha256", "HS256"), ("sha512", "HS512"), ("sha384", "HS384"), ("HS256", "HS256")],
)
async def test_jwt_algorithm_mapping(alg_field, expected):
    signed = await _node().run(
        ctx=None,
        params=_params(operation="jwt_sign", secret="k", algorithm=alg_field, claims={"a": 1}),
        input_items=[],
    )
    assert signed.output_items[0]["algorithm"] == expected


async def test_jwt_verify_rejects_the_wrong_secret():
    signed = await _node().run(
        ctx=None,
        params=_params(operation="jwt_sign", secret="right", claims={"sub": "u"}),
        input_items=[],
    )

    res = await _node().run(
        ctx=None,
        params=_params(operation="jwt_verify", secret="wrong", jwt_token=signed.output_items[0]["token"]),
        input_items=[],
    )
    assert res.output_items[0]["valid"] is False
    assert res.output_items[0]["reason"] == "invalid"


async def test_jwt_verify_rejects_alg_confusion():
    """A token signed with 'none' must not be accepted (CVE-2022-29217 class)."""
    import base64
    import json

    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'admin'})}."

    res = await _node().run(
        ctx=None, params=_params(operation="jwt_verify", secret="k", jwt_token=forged), input_items=[]
    )
    assert res.output_items[0]["valid"] is False


async def test_jwt_verify_reports_expiry_as_a_value():
    signed = await _node().run(
        ctx=None,
        params=_params(
            operation="jwt_sign", secret="k", claims={"sub": "u", "exp": int(time.time()) - 3600}
        ),
        input_items=[],
    )

    res = await _node().run(
        ctx=None,
        params=_params(operation="jwt_verify", secret="k", jwt_token=signed.output_items[0]["token"]),
        input_items=[],
    )
    assert res.output_items[0]["valid"] is False
    assert res.output_items[0]["reason"] == "expired"


async def test_jwt_verify_leeway_admits_a_recently_expired_token():
    signed = await _node().run(
        ctx=None,
        params=_params(
            operation="jwt_sign", secret="k", claims={"sub": "u", "exp": int(time.time()) - 60}
        ),
        input_items=[],
    )

    res = await _node().run(
        ctx=None,
        params=_params(
            operation="jwt_verify",
            secret="k",
            jwt_token=signed.output_items[0]["token"],
            leeway_seconds=300,
        ),
        input_items=[],
    )
    assert res.output_items[0]["valid"] is True


async def test_jwt_verify_enforces_issuer():
    signed = await _node().run(
        ctx=None,
        params=_params(operation="jwt_sign", secret="k", claims={"sub": "u", "iss": "flowsmith"}),
        input_items=[],
    )
    token = signed.output_items[0]["token"]

    ok = await _node().run(
        ctx=None,
        params=_params(operation="jwt_verify", secret="k", jwt_token=token, issuer="flowsmith"),
        input_items=[],
    )
    assert ok.output_items[0]["valid"] is True

    bad = await _node().run(
        ctx=None,
        params=_params(operation="jwt_verify", secret="k", jwt_token=token, issuer="someone-else"),
        input_items=[],
    )
    assert bad.output_items[0]["valid"] is False


async def test_jwt_verify_enforces_audience():
    signed = await _node().run(
        ctx=None,
        params=_params(operation="jwt_sign", secret="k", claims={"sub": "u", "aud": "flowsmith-api"}),
        input_items=[],
    )
    token = signed.output_items[0]["token"]

    ok = await _node().run(
        ctx=None,
        params=_params(operation="jwt_verify", secret="k", jwt_token=token, audience="flowsmith-api"),
        input_items=[],
    )
    assert ok.output_items[0]["valid"] is True

    bad = await _node().run(
        ctx=None,
        params=_params(operation="jwt_verify", secret="k", jwt_token=token, audience="other-api"),
        input_items=[],
    )
    assert bad.output_items[0]["valid"] is False


async def test_jwt_sign_requires_a_secret():
    with pytest.raises(NodeExecutionError) as exc:
        await _node().run(
            ctx=None, params=_params(operation="jwt_sign", claims={"a": 1}), input_items=[]
        )
    assert exc.value.code == "CRYPTO_KEY_MISSING"


async def test_jwt_verify_requires_a_token():
    with pytest.raises(NodeExecutionError) as exc:
        await _node().run(
            ctx=None, params=_params(operation="jwt_verify", secret="k"), input_items=[]
        )
    assert exc.value.code == "CRYPTO_JWT_MISSING_TOKEN"


async def test_existing_hash_operations_still_work():
    """The original operations must be untouched by the additions."""
    res = await _node().run(
        ctx=None, params=_params(operation="hash", text="abc", algorithm="sha256"), input_items=[]
    )
    assert res.output_items[0]["digest"] == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


async def test_existing_base64_and_hmac_operations_still_work():
    enc = await _node().run(
        ctx=None, params=_params(operation="base64_encode", text="hello"), input_items=[]
    )
    assert enc.output_items[0]["base64"] == "aGVsbG8="

    mac = await _node().run(
        ctx=None, params=_params(operation="hmac", text="hello", key="key", algorithm="sha256"),
        input_items=[],
    )
    # RFC 4231-style known-answer check rather than a self-comparison.
    assert mac.output_items[0]["hmac"] == (
        "9307b3b915efb5171ff14d8cb55fbcc798c6c0ef1456d66ded1a6aa723a58b7b"
    )
