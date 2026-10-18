"""Zero-downtime Credential Encryption Key Rotation CLI.

Rotates the CREDENTIALS_ENCRYPTION_KEY by:
1. Generating a new primary Fernet encryption key.
2. Loading all encrypted rows in `credentials` and `environments`.
3. Decrypting each row using the existing key ring.
4. Re-encrypting each row using the newly generated key.
5. Committing the re-encrypted rows transactionally.
6. Printing the updated CREDENTIALS_ENCRYPTION_KEY string for .env configuration.

Usage:
    python scripts/rotate_encryption_key.py [--apply] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend to sys.path so app modules resolve cleanly
ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import Credential, Environment
from app.security.crypto import decrypt_text


def rotate_keys(apply: bool = False) -> tuple[str, int, int]:
    new_key = Fernet.generate_key().decode()
    fernet_new = Fernet(new_key.encode())

    current_env = get_settings().credentials_encryption_key or ""
    existing_keys = [k.strip() for k in current_env.split(",") if k.strip()]
    updated_keyring = f"{new_key},{','.join(existing_keys)}" if existing_keys else new_key

    session = get_session()
    credentials_count = 0
    environments_count = 0

    try:
        # 1. Re-encrypt credentials table
        creds = session.scalars(select(Credential)).all()
        for c in creds:
            if not c.data:
                continue
            # Decrypt with current keyring
            raw_plaintext = decrypt_text(c.data)
            # Encrypt with new key
            new_token = fernet_new.encrypt(raw_plaintext.encode()).decode()
            if apply:
                c.data = f"k0:{new_token}"
            credentials_count += 1

        # 2. Re-encrypt environments table
        envs = session.scalars(select(Environment)).all()
        for e in envs:
            if not e.value or not e.value.startswith("k"):
                continue
            raw_plaintext = decrypt_text(e.value)
            new_token = fernet_new.encrypt(raw_plaintext.encode()).decode()
            if apply:
                e.value = f"k0:{new_token}"
            environments_count += 1

        if apply:
            session.commit()
            print(f"[OK] Transaction committed. Successfully re-encrypted:")
            print(f"  - {credentials_count} Credential records")
            print(f"  - {environments_count} Environment variable records")
        else:
            session.rollback()
            print(f"[DRY-RUN] Simulation successful. Would re-encrypt:")
            print(f"  - {credentials_count} Credential records")
            print(f"  - {environments_count} Environment variable records")

        return updated_keyring, credentials_count, environments_count
    except Exception as exc:
        session.rollback()
        print(f"[ERROR] Re-encryption failed: {exc}")
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Zero-downtime key rotation for Flowsmith.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit re-encrypted records to the database (defaults to dry-run)",
    )
    args = parser.parse_args()

    print("=== Flowsmith Key Rotation Utility ===")
    if not args.apply:
        print("[MODE] Running in DRY-RUN mode. Use --apply to execute.")
    else:
        print("[MODE] Running in APPLY mode. Changes will be committed.")

    new_keyring, c_count, e_count = rotate_keys(apply=args.apply)

    print("\nNext Steps for Zero-Downtime Deployment:")
    print("1. Update CREDENTIALS_ENCRYPTION_KEY in your .env.production:")
    print(f"   CREDENTIALS_ENCRYPTION_KEY={new_keyring}")
    print("2. Restart worker and app containers:")
    print("   docker compose restart app worker")
    print("3. Once confirmed operational, retired keys can be pruned from the tail of the keyring.\n")


if __name__ == "__main__":
    main()
