"""Encryption-key rotation CLI for every durable encrypted store.

Rotation is deliberately a two-phase operation so the app stays available:

1. Generate a new key and prepend it to ``CREDENTIALS_ENCRYPTION_KEY``
   (``NEW,OLD``), then restart app/worker. The old key remains readable.
2. Run this script with ``--apply``. It re-encrypts credentials,
   environment variables, MFA secrets, workflow auth state, provider
   webhook signing secrets, pending agent checkpoints, and account-export
   files with the new primary key.
3. Verify the app, then remove the old key after the rollback window.

``--dry-run`` (the default) never writes and reports how many records would
be rotated. It can also suggest a fresh key when the keyring has only one key.

Usage:
    python scripts/rotate_encryption_key.py --prepare
    # prepend the printed key to CREDENTIALS_ENCRYPTION_KEY and restart
    python scripts/rotate_encryption_key.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add backend to sys.path so app modules resolve cleanly
ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.db import get_session
from app.models import (
    Credential,
    Environment,
    Execution,
    ProviderWebhookRegistration,
    User,
    WorkflowAuthState,
)
from app.security.crypto import decrypt_text, encrypt_text
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

LAST_REPORT: dict[str, int] = {}


def _export_root(export_root: str | Path | None = None) -> Path:
    base = export_root or os.getenv("MAT_BACKUP_DIR") or "backups"
    return Path(base) / "users"


def _looks_encrypted(value: str) -> bool:
    text = value.strip()
    if text.startswith("v2:"):
        return True
    if text.startswith("{") and "ciphertext" in text:
        return True
    return bool(text[:1] == "k" and ":" in text[:8])


def _decrypt_or_plaintext(value: str) -> str:
    """Return plaintext for encrypted rows, or legacy plaintext unchanged.

    Tokens that *look* encrypted must decrypt; a failure aborts rotation
    instead of wrapping ciphertext as if it were plaintext.
    """
    return decrypt_text(value) if _looks_encrypted(value) else value


def _reencrypt_text(value: str) -> str:
    return encrypt_text(_decrypt_or_plaintext(value)).decode("ascii")


def _reencrypt_bytes(value: bytes) -> bytes:
    return encrypt_text(_decrypt_or_plaintext(value.decode("utf-8", errors="replace")))


def _reencrypt_pause_state(pause_state: dict | None) -> bool:
    """Re-encrypt the nested agent checkpoint blob, if present."""
    if not isinstance(pause_state, dict):
        return False
    blob = pause_state.get("state")
    if not isinstance(blob, str) or not blob:
        return False
    pause_state["state"] = _reencrypt_text(blob)
    return True


def rotate_exports(export_root: str | Path | None = None, *, apply: bool = False) -> int:
    """Re-encrypt account export files. Returns the number processed."""
    root = _export_root(export_root)
    if not root.exists():
        return 0
    count = 0
    for path in sorted(root.glob("*/*.json.enc")):
        token = path.read_bytes()
        plaintext = _decrypt_or_plaintext(token.decode("utf-8", errors="replace"))
        if apply:
            new_token = encrypt_text(plaintext)
            tmp = path.with_suffix(path.suffix + ".rotating")
            fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(new_token)
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        count += 1
    return count


def _counts() -> dict[str, int]:
    return dict(LAST_REPORT)


def rotate_keys(
    apply: bool = False,
    *,
    export_root: str | Path | None = None,
) -> tuple[str, int, int]:
    """Re-encrypt all durable secrets with the current primary key.

    When the keyring contains only one key and ``apply`` is false, a new key
    is suggested (printed by the CLI). ``apply`` requires the new key to be
    prepended already; this prevents a window where running app processes
    cannot decrypt freshly rotated rows.

    Returns ``(keyring, credential_count, environment_count)`` for backwards
    compatibility. Detailed counts are available in ``LAST_REPORT``.
    """
    global LAST_REPORT

    current_env = get_settings().credentials_encryption_key or ""
    existing_keys = [k.strip() for k in current_env.split(",") if k.strip()]
    prepared_key = Fernet.generate_key().decode()

    if apply and len(existing_keys) < 2:
        raise RuntimeError(
            "Refusing to rotate with a single key. Prepend the new key to "
            "CREDENTIALS_ENCRYPTION_KEY (NEW,OLD), restart app/worker, then "
            "run --apply so old rows remain readable during the pass."
        )

    suggested_keyring = (
        f"{prepared_key},{','.join(existing_keys)}"
        if existing_keys
        else prepared_key
    )
    keyring = current_env if len(existing_keys) >= 2 else suggested_keyring

    session = get_session()
    counts = {
        "credentials": 0,
        "environments": 0,
        "mfa_secrets": 0,
        "workflow_auth_state": 0,
        "provider_webhook_secrets": 0,
        "agent_checkpoints": 0,
        "export_files": 0,
    }
    try:
        creds = session.scalars(select(Credential)).all()
        for c in creds:
            if not c.data:
                continue
            new_blob = _reencrypt_bytes(c.data)
            if apply:
                c.data = new_blob
            counts["credentials"] += 1

        envs = session.scalars(select(Environment)).all()
        for e in envs:
            if not e.value:
                continue
            new_value = _reencrypt_text(e.value)
            if apply:
                e.value = new_value
            counts["environments"] += 1

        users = session.scalars(
            select(User).where(User.mfa_secret.is_not(None))
        ).all()
        for u in users:
            if not u.mfa_secret:
                continue
            new_secret = _reencrypt_text(u.mfa_secret)
            if apply:
                u.mfa_secret = new_secret
            counts["mfa_secrets"] += 1

        auth_states = session.scalars(select(WorkflowAuthState)).all()
        for state in auth_states:
            if not state.data:
                continue
            new_blob = _reencrypt_bytes(state.data)
            if apply:
                state.data = new_blob
            counts["workflow_auth_state"] += 1

        webhooks = session.scalars(select(ProviderWebhookRegistration)).all()
        for hook in webhooks:
            if not hook.signing_secret:
                continue
            new_secret = _reencrypt_bytes(hook.signing_secret)
            if apply:
                hook.signing_secret = new_secret
            counts["provider_webhook_secrets"] += 1

        executions = session.scalars(
            select(Execution).where(Execution.pause_state.is_not(None))
        ).all()
        for execution in executions:
            if _reencrypt_pause_state(execution.pause_state):
                # JSON columns do not detect in-place nested mutations.
                flag_modified(execution, "pause_state")
                counts["agent_checkpoints"] += 1

        if apply:
            session.commit()
        else:
            session.rollback()

        counts["export_files"] = rotate_exports(export_root, apply=apply)
        LAST_REPORT = counts
        return keyring, counts["credentials"], counts["environments"]
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate all Flowsmith encrypted data to the current primary key."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit re-encryption (requires NEW,OLD keyring). Default is dry-run.",
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Generate a candidate new key and exit without touching data.",
    )
    parser.add_argument(
        "--export-root",
        default=None,
        help="Base directory containing users/<id>/*.json.enc (default: MAT_BACKUP_DIR or backups).",
    )
    args = parser.parse_args()

    if args.prepare:
        print("Add this as the FIRST key in CREDENTIALS_ENCRYPTION_KEY:")
        print(f"  {Fernet.generate_key().decode()}")
        print("Then restart app/worker and run: python scripts/rotate_encryption_key.py --apply")
        return

    print("=== Flowsmith Key Rotation Utility ===")
    print("[MODE] APPLY" if args.apply else "[MODE] DRY-RUN")
    try:
        keyring, _, _ = rotate_keys(apply=args.apply, export_root=args.export_root)
    except RuntimeError as exc:
        print(f"[BLOCKED] {exc}")
        raise SystemExit(2) from exc

    counts = _counts()
    print(f"[{'OK' if args.apply else 'DRY-RUN'}] encrypted-store counts:")
    for name, count in counts.items():
        print(f"  - {name}: {count}")
    if not args.apply:
        print("\nNo changes written. To apply, prepend the new key, restart app/worker,")
        print("then re-run with --apply.")
    else:
        print("\nRe-encryption committed. Verify the app, then remove old key(s).")
        print(f"Current keyring: {keyring}")


if __name__ == "__main__":
    main()
