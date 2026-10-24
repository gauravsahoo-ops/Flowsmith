"""Generate Ed25519 keys and sign connector-pack manifests.

Examples (from ``backend/``)::

    python scripts/sign_connector_pack.py keygen \
        --key-id release-2026 \
        --private-key pack-private.pem \
        --public-key pack-public.txt

    python scripts/sign_connector_pack.py sign \
        --manifest pack.json \
        --private-key pack-private.pem \
        --key-id release-2026 \
        --output pack.signed.json

Put the public-key file contents into ``CONNECTOR_PACK_TRUSTED_KEYS`` as::

    {"release-2026":"<contents of pack-public.txt>"}

Keep the private key offline; never commit it.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.connector_pack_signing import sign_manifest  # noqa: E402


def _keygen(args: argparse.Namespace) -> int:
    private = Ed25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    Path(args.private_key).write_bytes(private_bytes)
    Path(args.public_key).write_text(
        base64.b64encode(raw_public).decode("ascii") + "\n",
        encoding="utf-8",
    )
    print(f"private key: {args.private_key}")
    print(f"public key:  {args.public_key}")
    print(f"key id:      {args.key_id}")
    return 0


def _sign(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("Manifest must be a JSON object.")
    private = serialization.load_pem_private_key(
        Path(args.private_key).read_bytes(),
        password=None,
    )
    if not isinstance(private, Ed25519PrivateKey):
        raise SystemExit("Private key must be an Ed25519 key.")
    signed = sign_manifest(manifest, private, args.key_id)
    output = Path(args.output) if args.output else Path(args.manifest)
    output.write_text(json.dumps(signed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"signed manifest: {output}")
    print(f"signing key id:  {args.key_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="Generate an Ed25519 key pair.")
    keygen.add_argument("--key-id", required=True)
    keygen.add_argument("--private-key", required=True)
    keygen.add_argument("--public-key", required=True)
    keygen.set_defaults(func=_keygen)

    sign = sub.add_parser("sign", help="Sign a connector-pack manifest.")
    sign.add_argument("--manifest", required=True)
    sign.add_argument("--private-key", required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--output", default="")
    sign.set_defaults(func=_sign)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
