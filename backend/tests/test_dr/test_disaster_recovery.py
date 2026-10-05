"""Phase 33 — disaster-recovery tests.

The centerpiece runs the FULL drill against real PostgreSQL: seed →
pg_dump → restore into a fresh database → damage the target → restore
again (fresh mode) → verify every recovery claim through app code
paths. Skips cleanly only when no PostgreSQL server is reachable.

Worker/API recovery evidence lives in test_queue/test_worker_recovery.py,
test_db_queue.py (stale-claim requeue) and
test_api/test_async_worker_recovery.py (API restart); this suite adds
the data-plane guarantees.
"""

from __future__ import annotations

import socket

import pytest

from app.utils.backup import list_backups, prune_backups


def _postgres_reachable() -> bool:
    try:
        try:
            import psycopg
            conn = psycopg.connect(
                host="127.0.0.1", port=5432, user="automate",
                password="automate", dbname="postgres", connect_timeout=3,
            )
        except ImportError:
            import psycopg2
            conn = psycopg2.connect(
                host="127.0.0.1", port=5432, user="automate",
                password="automate", dbname="postgres", connect_timeout=3,
            )
        conn.close()
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(
    not _postgres_reachable(), reason="PostgreSQL not reachable on 127.0.0.1:5432",
)


@requires_pg
def test_full_disaster_recovery_drill(tmp_path):
    """THE evidence: a real backup really recovers a really damaged database."""
    from app.dr import run_drill

    report = run_drill(work_dir=tmp_path)
    assert report["ok"] is True, report
    assert all(report["checks"].values()), report["checks"]

    rto = report["rto_seconds"]
    # A tiny dataset must restore in seconds, not minutes — guards against
    # silent transport regressions (e.g. raw-gzip-stdin bug class).
    assert rto["restore"] < 60
    assert rto["restore_over_damage"] < 60


@requires_pg
def test_restored_credential_requires_the_encryption_key(tmp_path, monkeypatch):
    """Credential recovery is bound to CREDENTIALS_ENCRYPTION_KEY: the row
    restores fine, decryption succeeds with the right key and hard-fails
    (never silent garbage) with a wrong one."""
    import uuid

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import get_settings
    from app.db import Base
    from app.models import Credential
    from app.security.crypto import CredentialDecryptionError, decrypt_text
    from app.utils.backup import create_backup, restore_backup

    base = get_settings().database_url.rsplit("/", 1)[0]
    suffix = uuid.uuid4().hex[:8]
    src = f"{base}/drill_cred_src_{suffix}"
    tgt = f"{base}/drill_cred_tgt_{suffix}"

    admin = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.begin() as conn:
        conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{src.rsplit("/", 1)[-1]}"')
        conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{tgt.rsplit("/", 1)[-1]}"')
        conn.exec_driver_sql(f'CREATE DATABASE "{src.rsplit("/", 1)[-1]}"')
        conn.exec_driver_sql(f'CREATE DATABASE "{tgt.rsplit("/", 1)[-1]}"')

    try:
        from app.dr import damage_target, seed_source, verify_target

        facts = seed_source(src)
        dump = create_backup("cred_drill", dsn=src, out_dir=tmp_path)
        restore_backup(dump, dsn=tgt)
        damage_target(tgt)
        restore_backup(dump, dsn=tgt, fresh=True)

        checks = verify_target(tgt, facts)
        assert checks["credentials"] is True

        engine = create_engine(tgt)
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            cred = db.get(Credential, "cred_drill")
            blob = bytes(cred.data)
        finally:
            db.close()
            engine.dispose()

        # Right key -> plaintext recovered (credential recovery works).
        decrypted = decrypt_text(blob)
        assert facts["secret_api_key"] in decrypted

        # Wrong key -> typed hard failure.
        monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "totally-wrong-key-material")
        from app.config import get_settings
        get_settings.cache_clear()
        try:
            with pytest.raises(CredentialDecryptionError):
                decrypt_text(blob)
        finally:
            # Restore original key for cleanup
            monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEY", raising=False)
            get_settings.cache_clear()
    finally:
        with admin.begin() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{src.rsplit("/", 1)[-1]}"')
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{tgt.rsplit("/", 1)[-1]}"')


def test_backup_listing_and_retention_pruning(tmp_path):
    from datetime import UTC, datetime, timedelta
    import os

    old = tmp_path / "backup_old.sql.gz"
    new = tmp_path / "backup_new.sql.gz"
    for p in (old, new):
        p.write_bytes(b"x")
    past = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(old, (past, past))

    names = {b["filename"] for b in list_backups(tmp_path)}
    assert {"backup_old.sql.gz", "backup_new.sql.gz"} <= names

    removed = prune_backups(keep_days=14, out_dir=tmp_path)
    assert removed == 1
    assert new.exists() and not old.exists()


def test_drill_skips_gracefully_without_postgres(monkeypatch, tmp_path):
    """If no Postgres is reachable the drill reports failure instead of
    hanging or crashing — CI without a database stays green."""
    if _postgres_reachable():
        pytest.skip("Postgres reachable; skip-safety path not exercised")
    from app.dr import run_drill

    report = run_drill(work_dir=tmp_path)
    assert report["ok"] is False
