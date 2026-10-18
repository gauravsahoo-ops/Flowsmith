"""Production secret generator for Flowsmith.

Generates high-entropy, cryptographically secure keys for:
- JWT_SECRET (min 256-bit entropy for HS256)
- CREDENTIALS_ENCRYPTION_KEY (Fernet / AES-256 key)
- POSTGRES_PASSWORD (Database authentication)
- REDIS_PASSWORD (Queue broker authentication)
- GRAFANA_PASSWORD (Monitoring dashboard authentication)

Usage:
    python scripts/generate_production_secrets.py [--env-file .env.production]
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def generate_secrets() -> dict[str, str]:
    return {
        "JWT_SECRET": secrets.token_urlsafe(48),
        "CREDENTIALS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "REDIS_PASSWORD": secrets.token_urlsafe(24),
        "GRAFANA_PASSWORD": secrets.token_urlsafe(20),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate production secrets for Flowsmith.")
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional path to .env file to update with generated secrets",
    )
    args = parser.parse_args()

    sec = generate_secrets()

    if args.env_file:
        target = Path(args.env_file)
        if not target.exists():
            print(f"[ERROR] Target file not found: {target}")
            raise SystemExit(1)

        content = target.read_text(encoding="utf-8")
        lines = content.splitlines()
        updated_lines = []
        replaced_keys = set()

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                updated_lines.append(line)
                continue
            if "=" in line:
                k, _ = line.split("=", 1)
                k = k.strip()
                if k in sec:
                    updated_lines.append(f"{k}={sec[k]}")
                    replaced_keys.add(k)
                    continue
            updated_lines.append(line)

        # Append any keys that weren't present in the file
        for k, v in sec.items():
            if k not in replaced_keys:
                updated_lines.append(f"{k}={v}")

        target.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
        print(f"[OK] Successfully updated {target} with fresh production secrets:")
        for k in sec:
            print(f"  - {k}: [GENERATED AND SAVED]")
    else:
        print("=== GENERATED PRODUCTION SECRETS ===")
        for k, v in sec.items():
            print(f"{k}={v}")


if __name__ == "__main__":
    main()
