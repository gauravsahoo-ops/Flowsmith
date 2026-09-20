"""Disaster-recovery drill (Phase 33).

Runs a REAL backup → damage → restore → verify cycle against throwaway
PostgreSQL databases and returns an evidence report::

    {
      "ok": true,
      "rto_seconds": {...},          # measured: dump / restore / verify / total
      "rpo": {...},                  # recovery-point accounting
      "checks": {"users": true, "workflows": true,
                 "credentials": true, "executions": true,
                 "damage_repaired": true},
      "databases": {"source": "...", "target": "..."},
      "backup": {"file": "...", "size_mb": ...},
    }

No production database is touched: the drill provisions two scratch
databases on the same server, seeds the source THROUGH THE APP MODELS
(so what we verify is what the application would read back), damages
the target, restores over the damage and verifies every recovery claim
of docs/DISASTER_RECOVERY.md.

RPO model (see docs): the dump captures all committed writes at dump
time; with scheduled backups RPO == schedule interval. Workers/Redis
lose only queued jobs (executions table is authoritative).
"""

from __future__ import annotations

import secrets
import time
import uuid
from typing import Any

from sqlalchemy import create_engine, text

from app.utils.backup import create_backup, restore_backup

ADMIN_DSN_TEMPLATE = (
    "postgresql://{user}:{password}@{host}:{port}/postgres"
)


def _admin_engine(dsn: str):
    from sqlalchemy.engine import make_url

    url = make_url(dsn)
    admin_url = url.set(database="postgres", drivername="postgresql+psycopg2")
    return create_engine(admin_url, isolation_level="AUTOCOMMIT")


def _create_db(admin_engine, name: str) -> None:
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        ).fetchone()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{name}"'))


def _drop_db(admin_engine, name: str) -> None:
    with admin_engine.connect() as conn:
        conn.execute(text(
            'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
            'WHERE datname = :n AND pid <> pg_backend_pid()'
        ), {"n": name})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


# ----------------------------------------------------------------------
# seeding & verification (through app models — never raw SQL fixtures)
# ----------------------------------------------------------------------

def seed_source(database_url: str) -> dict[str, Any]:
    """Create schema + representative rows; returns verification facts."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.models import (
        Credential,
        Execution,
        User,
        WorkflowRecord,
        WorkspaceMember,
    )
    from app.models.organization import Organization, Workspace, WorkflowVersionRecord
    from app.security.crypto import encrypt_text

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    facts: dict[str, Any] = {}
    try:
        alice = User(email="dr-alice@example.com", password_hash="hashed-a")
        bob = User(email="dr-bob@example.com", password_hash="hashed-b")
        db.add_all([alice, bob])
        db.flush()

        org = Organization(id="org_drill", name="dr-org", founder_id=alice.id)
        ws = Workspace(id="ws_drill", name="dr-ws",
                       organization_id=org.id, creator_id=alice.id)
        db.add_all([org, ws])
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=alice.id,
                               role="owner", permission="edit"))

        wf_data = {
            "id": "wf_drill", "name": "DR Drill Workflow", "status": "active",
            "nodes": [
                {"id": "t", "type": "manual_trigger", "parameters": {}},
                {"id": "x", "type": "set_data",
                 "parameters": {"fields": {"greeting": "survived"}}},
            ],
            "connections": [{"source": "t", "target": "x"}],
            "settings": {},
        }
        rec = WorkflowRecord(id="wf_drill", user_id=alice.id,
                             name="DR Drill Workflow", version=2,
                             data=wf_data, workspace_id=ws.id)
        ver = WorkflowVersionRecord(
            id="ver_drill", workflow_id="wf_drill", version=1,
            data=wf_data, user_id=alice.id, is_active=True,
        )
        db.add_all([rec, ver])

        secret = f"sk-live-{secrets.token_hex(16)}"
        blob = encrypt_text(__import__("json").dumps(
            {"base_url": "https://api.example.com", "api_key": secret}))
        cred = Credential(id="cred_drill", user_id=alice.id, name="dr-cred",
                          type="llm", data=blob)
        db.add(cred)

        execution = Execution(
            id="exec_drill", workflow_id="wf_drill", user_id=alice.id,
            workflow_version=2, trigger="manual", status="success",
            workflow_data=wf_data,
            trigger_data=[{"q": 1}],
            results={"outputs": {"x": {"main": [{"greeting": "survived"}]}}},
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        db.add(execution)
        db.commit()

        facts.update({
            "secret_api_key": secret,
            "workflow_id": "wf_drill",
            "credential_id": "cred_drill",
            "execution_id": "exec_drill",
            "user_emails": sorted(["dr-alice@example.com", "dr-bob@example.com"]),
        })
        return facts
    finally:
        db.close()
        engine.dispose()


def verify_target(database_url: str, facts: dict[str, Any]) -> dict[str, bool]:
    """Read the restored database back THROUGH app code paths."""
    checks: dict[str, bool] = {}
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.security.crypto import decrypt_text
    from app.db import Base
    from app.models import Credential, Execution, User, WorkflowRecord
    from app.schemas.workflow import Workflow

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)  # no-op when restore built the schema
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        emails = sorted(r[0] for r in db.execute(select(User.email)).all())
        checks["users"] = emails == facts["user_emails"]

        wf_rec = db.get(WorkflowRecord, facts["workflow_id"])
        checks["workflows"] = False
        if wf_rec is not None:
            # The stored graph must still load through the real schema.
            Workflow.model_validate(wf_rec.data)
            checks["workflows"] = wf_rec.name == "DR Drill Workflow"

        cred = db.get(Credential, facts["credential_id"])
        checks["credentials"] = False
        if cred is not None:
            decrypted = decrypt_text(cred.data)
            checks["credentials"] = facts["secret_api_key"] in decrypted

        ex = db.get(Execution, facts["execution_id"])
        checks["executions"] = bool(
            ex is not None and ex.status == "success" and ex.results is not None
            and ex.results["outputs"]["x"]["main"][0]["greeting"] == "survived"
        )
        return checks
    finally:
        db.close()
        engine.dispose()


def damage_target(database_url: str) -> None:
    """Simulate corruption: trash the most valuable tables in place."""
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE workflows SET name = 'CATASTROPHIC DAMAGE', "
            "data = '{\"broken\": true}'"
        ))
        conn.execute(text("UPDATE credentials SET data = 'corrupted-blob'"))
        conn.execute(text("DELETE FROM executions"))
    engine.dispose()


# ----------------------------------------------------------------------
# the drill
# ----------------------------------------------------------------------

def run_drill(base_dsn: str | None = None, *, work_dir=None) -> dict[str, Any]:
    """Full DR cycle against throwaway databases. Returns the report."""
    t_start = time.perf_counter()
    settings_dsn = base_dsn
    if settings_dsn is None:
        from app.config import get_settings

        settings_dsn = get_settings().database_url
    from sqlalchemy.engine import make_url

    base_url = make_url(settings_dsn)
    suffix = uuid.uuid4().hex[:8]
    source_db = f"drill_source_{suffix}"
    target_db = f"drill_target_{suffix}"

    src_dsn = base_url.set(database=source_db).render_as_string(hide_password=False)
    tgt_dsn = base_url.set(database=target_db).render_as_string(hide_password=False)
    admin = _admin_engine(settings_dsn)
    report: dict[str, Any] = {"ok": False, "checks": {}, "rto_seconds": {}, "rpo": {}}
    try:
        _create_db(admin, source_db)
        _create_db(admin, target_db)

        facts = seed_source(src_dsn)

        # --- backup -----------------------------------------------------
        t0 = time.perf_counter()
        backup_path = create_backup(f"drill_{suffix}", dsn=src_dsn,
                                    out_dir=work_dir or "backups/drill")
        dump_s = round(time.perf_counter() - t0, 2)

        # --- restore over a HEALTHY target first ------------------------
        t0 = time.perf_counter()
        restore_backup(backup_path, dsn=tgt_dsn)
        restore_s = round(time.perf_counter() - t0, 2)

        # --- damage + restore again (recovery must REPAIR) ---------------
        damage_target(tgt_dsn)
        t0 = time.perf_counter()
        restore_backup(backup_path, dsn=tgt_dsn, fresh=True)
        repair_s = round(time.perf_counter() - t0, 2)

        # --- verify -------------------------------------------------------
        t0 = time.perf_counter()
        checks = verify_target(tgt_dsn, facts)
        verify_s = round(time.perf_counter() - t0, 2)
        checks["damage_repaired"] = all(checks.values())

        total_s = round(time.perf_counter() - t_start, 2)
        size_mb = round(backup_path.stat().st_size / (1024 * 1024), 3)
        report.update({
            "ok": all(checks.values()),
            "checks": checks,
            "rto_seconds": {
                "dump": dump_s, "restore": restore_s,
                "restore_over_damage": repair_s, "verify": verify_s,
                "total_measured": total_s,
            },
            "rpo": {
                "model": "scheduled pg_dump",
                "committed_writes_lost": "writes AFTER the last dump",
                "queue_jobs": "in-flight jobs may need manual re-trigger "
                              "(executions table is authoritative)",
                "credentials_note": "restores require CREDENTIALS_ENCRYPTION_KEY "
                                    "(kept outside the database)",
            },
            "databases": {"source": source_db, "target": target_db},
            "backup": {"file": str(backup_path), "size_mb": size_mb},
        })
        return report
    finally:
        try:
            _drop_db(admin, source_db)
            _drop_db(admin, target_db)
        except Exception:  # noqa: BLE001 — cleanup must never mask the result
            pass
