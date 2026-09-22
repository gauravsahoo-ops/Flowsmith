"""Credential key rotation helper.

Usage:
  1. Prepend the NEW key to CREDENTIALS_ENCRYPTION_KEY (comma-separated).
  2. Run:  python -m app.scripts.rotate_credentials
     (re-encrypts every stored credential with the new first key)
  3. Remove the OLD key from CREDENTIALS_ENCRYPTION_KEY.
"""

from __future__ import annotations

import sys

from app.db import get_session, init_db
from app.security.crypto import _keys

if __name__ == "__main__":
    init_db()
    db = get_session()
    try:
        keys = _keys()
        if len(keys) < 2:
            print("No rotation needed: CREDENTIALS_ENCRYPTION_KEY has a single key.")
            sys.exit(0)
        from app.credentials.service import reencrypt_all

        count = reencrypt_all(db)
        print(f"Re-encrypted {count} credential(s) with key #0.")
        print("Now remove the old key(s) from CREDENTIALS_ENCRYPTION_KEY.")
    finally:
        db.close()
