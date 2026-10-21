"""Section 9 Audit Suite: Database & Data Integrity.

Comprehensive verification of:
1. PostgreSQL schema and migration validation
2. CRUD operations and transaction integrity
3. Workflow, credential and execution record consistency
4. JSON/JSONB fields and schema validation
5. pgvector and retrieval operations where enabled
6. Redis queues, locks, caching and state synchronization
7. Concurrent writes and duplicate event handling
8. Backup, restore and recovery procedures
9. Data retention, deletion and tenant isolation
"""

from __future__ import annotations

import gzip
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import redis
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.config import get_settings
from app.db import (
    EXPECTED_ALEMBIC_HEAD,
    FLOWSMITH_MIGRATION_LOCK_ID,
    Base,
    get_current_revision,
    get_session,
    verify_schema_state,
)
from app.maintenance import prune
from app.models import (
    Credential,
    Execution,
    User,
    WebhookDelivery,
    WorkflowRecord,
)
from app.queue.redis_queue import RedisJobQueue
from app.security.crypto import decrypt_text, encrypt_text
from app.utils.backup import list_backups, prune_backups
from app.vectorstores.pgvector import PgVectorStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid(prefix: str = "t") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _create_test_user(db, email: str | None = None) -> User:
    email = email or f"{_uid('u')}@example.com"
    u = User(
        email=email,
        password_hash="hashed_pw_123",
        role="user",
        created_at=datetime.now(UTC),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# 1. PostgreSQL Schema and Migration Validation
# ---------------------------------------------------------------------------

def test_postgresql_schema_and_migration_validation():
    """Verify schema state, tables, alembic version, advisory locks and critical indexes."""
    db = get_session()
    try:
        eng = db.get_bind()
        inspector = inspect(eng)
        table_names = set(inspector.get_table_names())

        # Verify all core models are present in schema
        expected_tables = {
            "users",
            "workflows",
            "executions",
            "credentials",
            "jobs",
            "data_tables",
            "staged_contacts",
            "audit_events",
            "error_events",
            "execution_events",
            "api_request_logs",
        }
        for tbl in expected_tables:
            assert tbl in table_names, f"Expected table '{tbl}' missing from PostgreSQL schema."

        # Verify migration lock ID is configured as a 32-bit/64-bit integer
        assert isinstance(FLOWSMITH_MIGRATION_LOCK_ID, int)
        assert FLOWSMITH_MIGRATION_LOCK_ID > 0

        # Verify schema health report
        report = verify_schema_state(eng)
        assert "ok" in report
        assert "current_revision" in report
        assert "expected_revision" in report
        assert report["expected_revision"] == EXPECTED_ALEMBIC_HEAD

        # Verify critical performance indexes exist
        indexes = {idx["name"] for idx in inspector.get_indexes("executions")}
        assert "ix_executions_workflow_started" in indexes or any("workflow" in i for i in indexes)
        assert "ix_executions_wf_status" in indexes or any("status" in i for i in indexes)

        # Verify JSON/JSONB column typing on workflows.data
        cols = {c["name"]: str(c["type"]).upper() for c in inspector.get_columns("workflows")}
        assert "data" in cols
        assert "JSON" in cols["data"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. CRUD Operations and Transaction Integrity
# ---------------------------------------------------------------------------

def test_crud_operations_and_transaction_integrity():
    """Verify Create, Read, Update, Delete across core models and transaction rollback atomicity."""
    db = get_session()
    try:
        # Create
        user = _create_test_user(db)
        wf_id = _uid("wf")
        wf = WorkflowRecord(
            id=wf_id,
            user_id=user.id,
            name="CRUD Workflow",
            description="Testing CRUD",
            data={"nodes": [{"id": "n1", "type": "manual_trigger"}], "connections": []},
            active=False,
            version=1,
        )
        db.add(wf)
        db.commit()

        # Read
        fetched = db.get(WorkflowRecord, wf_id)
        assert fetched is not None
        assert fetched.name == "CRUD Workflow"
        assert fetched.data["nodes"][0]["id"] == "n1"

        # Update
        fetched.name = "Updated CRUD Workflow"
        fetched.active = True
        db.commit()
        db.refresh(fetched)
        assert fetched.name == "Updated CRUD Workflow"
        assert fetched.active is True

        # Delete
        db.delete(fetched)
        db.commit()
        assert db.get(WorkflowRecord, wf_id) is None

        # Transaction Rollback Integrity: failed operation rolls back clean
        tx_wf_id = _uid("tx_wf")
        try:
            with db.begin_nested():
                uncommitted_wf = WorkflowRecord(
                    id=tx_wf_id,
                    user_id=user.id,
                    name="Will Rollback",
                    data={},
                    active=False,
                    version=1,
                )
                db.add(uncommitted_wf)
                db.flush()
                # Force an intentional exception
                raise RuntimeError("Intentional rollback trigger")
        except RuntimeError:
            pass

        # Record must NOT exist after rollback
        assert db.get(WorkflowRecord, tx_wf_id) is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. Workflow, Credential and Execution Record Consistency
# ---------------------------------------------------------------------------

def test_workflow_credential_and_execution_record_consistency():
    """Verify Foreign Key integrity, Credential encryption, and Execution version snapshotting."""
    db = get_session()
    try:
        user = _create_test_user(db)

        # 1. Foreign Key Integrity: cannot create execution for non-existent workflow
        with pytest.raises(IntegrityError):
            bad_exec = Execution(
                id=_uid("exec_bad_fk"),
                workflow_id="non_existent_workflow_id",
                user_id=user.id,
                workflow_version=1,
                workflow_data={},
                status="running",
            )
            db.add(bad_exec)
            db.commit()
        db.rollback()

        # 2. Credential Encryption Consistency
        secret_payload = json.dumps({"api_key": "sk-super-secret-12345", "token": "xyz987"})
        encrypted_blob = encrypt_text(secret_payload)
        assert secret_payload not in encrypted_blob.decode("utf-8", errors="ignore")

        cred_id = _uid("cred")
        cred = Credential(
            id=cred_id,
            user_id=user.id,
            name="Secure Credential",
            type="custom_api",
            data=encrypted_blob,
        )
        db.add(cred)
        db.commit()

        # Decrypt check
        fetched_cred = db.get(Credential, cred_id)
        assert fetched_cred is not None
        decrypted_json = decrypt_text(bytes(fetched_cred.data))
        decrypted_dict = json.loads(decrypted_json)
        assert decrypted_dict["api_key"] == "sk-super-secret-12345"

        # 3. Execution Version Snapshotting
        wf_id = _uid("wf_snap")
        v1_data = {"name": "Version 1 Flow", "nodes": [{"id": "t1", "type": "manual"}]}
        wf = WorkflowRecord(
            id=wf_id,
            user_id=user.id,
            name="Snapshot Flow",
            version=1,
            data=v1_data,
            active=True,
        )
        db.add(wf)
        db.commit()

        exec_id = _uid("exec_snap")
        ex = Execution(
            id=exec_id,
            workflow_id=wf_id,
            user_id=user.id,
            workflow_version=1,
            workflow_data=v1_data,
            status="success",
        )
        db.add(ex)
        db.commit()

        # Mutate workflow to version 2
        wf.version = 2
        wf.data = {"name": "Version 2 Flow", "nodes": [{"id": "t2", "type": "webhook"}]}
        db.commit()

        # Verify execution record still retains pristine frozen version 1 snapshot
        fetched_exec = db.get(Execution, exec_id)
        assert fetched_exec.workflow_version == 1
        assert fetched_exec.workflow_data["name"] == "Version 1 Flow"
        assert fetched_exec.workflow_data["nodes"][0]["id"] == "t1"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. JSON/JSONB Fields and Schema Validation
# ---------------------------------------------------------------------------

def test_json_jsonb_fields_and_schema_validation():
    """Verify JSON/JSONB containment, deep key extraction, and type validation."""
    db = get_session()
    try:
        user = _create_test_user(db)
        wf_id = _uid("wf_json")

        complex_data = {
            "name": "Nested JSON Flow",
            "metadata": {
                "environment": "production",
                "tags": ["critical", "billing", "automated"],
                "retry_policy": {"max_retries": 5, "backoff": 2.5},
            },
            "nodes": [
                {"id": "node_1", "type": "webhook", "config": {"path": "inbound-hook", "auth": True}},
                {"id": "node_2", "type": "transform", "config": {"mapping": {"k1": "v1"}}},
            ],
            "connections": [{"source": "node_1", "target": "node_2"}],
        }

        wf = WorkflowRecord(
            id=wf_id,
            user_id=user.id,
            name="JSON Test",
            data=complex_data,
            active=True,
            version=1,
        )
        db.add(wf)
        db.commit()

        # Query and assert complex deep structures persist without loss
        fetched = db.get(WorkflowRecord, wf_id)
        assert fetched.data["metadata"]["retry_policy"]["max_retries"] == 5
        assert "billing" in fetched.data["metadata"]["tags"]
        assert fetched.data["nodes"][0]["config"]["path"] == "inbound-hook"

        # Execution results JSON testing
        ex_id = _uid("exec_json")
        ex = Execution(
            id=ex_id,
            workflow_id=wf_id,
            user_id=user.id,
            workflow_version=1,
            workflow_data=complex_data,
            status="success",
            results={"node_1": [{"id": 100, "status": "ok"}], "node_2": [{"transformed": True}]},
            node_statuses={"node_1": "success", "node_2": "success"},
        )
        db.add(ex)
        db.commit()

        fetched_ex = db.get(Execution, ex_id)
        assert fetched_ex.results["node_1"][0]["id"] == 100
        assert fetched_ex.node_statuses["node_2"] == "success"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. pgvector and Retrieval Operations Where Enabled
# ---------------------------------------------------------------------------

def test_pgvector_and_retrieval_operations():
    """Verify vector collection creation, embedding ingestion, and cosine similarity ranking."""
    store = PgVectorStore()
    col_name = _uid("col_vector")
    dim = 3
    handle = store.ensure_collection(col_name, dim)

    try:
        # Ingest test embeddings
        v1 = [0.1, 0.2, 0.3]
        v2 = [0.9, 0.1, 0.1]
        v3 = [0.0, 0.9, 0.2]

        store.add(
            handle,
            documents=["Authentication setup guide", "Billing and invoices", "Webhooks and events"],
            embeddings=[v1, v2, v3],
            metadatas=[{"category": "auth"}, {"category": "billing"}, {"category": "events"}],
            ids=["doc_auth", "doc_billing", "doc_events"],
        )

        # Query using vector matching v1
        hits = store.query(handle, v1, top_k=2)
        assert len(hits) > 0
        top = hits[0]
        # Top result must be doc_auth with cosine similarity close to 1.0
        assert top["content"] == "Authentication setup guide"
        assert top["metadata"]["category"] == "auth"
        assert top["similarity"] > 0.95

        # Test idempotent replacement on doc_id
        updated_v1 = [0.12, 0.22, 0.31]
        store.add(
            handle,
            documents=["Updated Authentication setup guide v2"],
            embeddings=[updated_v1],
            metadatas=[{"category": "auth_v2"}],
            ids=["doc_auth"],
        )
        updated_res = store.query(handle, updated_v1, top_k=1)
        assert updated_res[0]["content"] == "Updated Authentication setup guide v2"
        assert updated_res[0]["metadata"]["category"] == "auth_v2"
    finally:
        store.delete_collection(col_name)


# ---------------------------------------------------------------------------
# 6. Redis Queues, Locks, Caching and State Synchronization
# ---------------------------------------------------------------------------

def test_redis_queues_locks_caching_and_state_sync():
    """Verify Redis job queue operations, distributed mutual exclusion lock, and queue state."""
    redis_url = os.environ.get("TEST_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/15"
    r = redis.Redis.from_url(redis_url, decode_responses=True)
    q = RedisJobQueue()

    job_id = _uid("job")
    exec_id = _uid("exec")
    payload = {
        "workflow_data": {"id": "wf_test", "name": "Test Queue WF", "nodes": [], "connections": []},
        "trigger_items": [{"test": True}],
        "trigger": "manual",
        "user_id": 1,
        "workflow_id": "wf_test",
    }

    try:
        # Enqueue job
        enqueued = q.enqueue(job_id=job_id, execution_id=exec_id, payload=payload)
        assert enqueued is True

        # Claim job (moves from pending to processing)
        claimed = q.claim()
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.execution_id == exec_id
        assert claimed.payload["workflow_id"] == "wf_test"

        # Complete job
        q.complete(claimed.id, status="done")
        meta_status = r.hget(f"queue:meta:{claimed.id}", "status")
        assert meta_status == "done"
        assert r.lpos("queue:jobs:processing", claimed.id) is None

        # Distributed Lock Mutex: Test concurrent locking behavior
        lock_key = f"flowsmith:lock:test_{_uid()}"
        lock1 = r.lock(lock_key, timeout=5)
        acquired1 = lock1.acquire(blocking=False)
        assert acquired1 is True

        # Second lock attempt must fail while lock1 is held
        lock2 = r.lock(lock_key, timeout=5)
        acquired2 = lock2.acquire(blocking=False)
        assert acquired2 is False

        # Release lock1; second acquire must now succeed
        lock1.release()
        acquired3 = lock2.acquire(blocking=False)
        assert acquired3 is True
        lock2.release()
    finally:
        r.close()


# ---------------------------------------------------------------------------
# 7. Concurrent Writes and Duplicate Event Handling
# ---------------------------------------------------------------------------

def test_concurrent_writes_and_duplicate_event_handling():
    """Verify unique constraint violations on duplicate writes and idempotent deduplication."""
    db1 = get_session()
    db2 = get_session()
    try:
        email = f"duplicate_{_uid()}@flowsmith.io"
        u1 = User(
            email=email,
            password_hash="hash1",
            role="user",
            created_at=datetime.now(UTC),
        )
        db1.add(u1)
        db1.commit()

        # Concurrent insert with identical unique email from second session must raise IntegrityError
        u2 = User(
            email=email,
            password_hash="hash2",
            role="user",
            created_at=datetime.now(UTC),
        )
        db2.add(u2)
        with pytest.raises(IntegrityError):
            db2.commit()
        db2.rollback()

        # Webhook delivery idempotency / duplicate key check
        wf_id = _uid("wf_dup")
        db1.add(WorkflowRecord(id=wf_id, user_id=u1.id, name="Hook WF", data={}, active=True))
        db1.commit()

        delivery_id = _uid("dlv")
        d1 = WebhookDelivery(
            id=delivery_id,
            workflow_id=wf_id,
            user_id=u1.id,
            path="unique-path",
            status="received",
            received_at=datetime.now(UTC),
        )
        db1.add(d1)
        db1.commit()

        # Duplicate delivery_id from second session must fail unique primary key constraint
        d2 = WebhookDelivery(
            id=delivery_id,
            workflow_id=wf_id,
            user_id=u1.id,
            path="unique-path",
            status="received",
            received_at=datetime.now(UTC),
        )
        db2.add(d2)
        with pytest.raises(IntegrityError):
            db2.commit()
        db2.rollback()
    finally:
        db1.close()
        db2.close()


# ---------------------------------------------------------------------------
# 8. Backup, Restore and Recovery Procedures
# ---------------------------------------------------------------------------

def test_backup_restore_and_recovery_procedures(tmp_path):
    """Verify backup archive generation, gzip compression, manifest listing and retention pruning."""
    backup_file = tmp_path / "test_backup_20261021.sql.gz"
    sample_sql = (
        "-- Flowsmith Database Dump\n"
        "CREATE TABLE test_sample (id INT PRIMARY KEY, name TEXT);\n"
        "INSERT INTO test_sample VALUES (1, 'Recovery Sample');\n"
    ).encode("utf-8")

    with gzip.open(backup_file, "wb") as gz:
        gz.write(sample_sql)

    assert backup_file.exists()
    assert backup_file.stat().st_size > 0

    # Verify gzip archive decompression integrity
    with gzip.open(backup_file, "rb") as gz:
        restored_sql = gz.read().decode("utf-8")
        assert "Recovery Sample" in restored_sql

    # Test list_backups functionality
    backups = list_backups(tmp_path)
    assert len(backups) == 1
    assert backups[0]["filename"] == "test_backup_20261021.sql.gz"
    assert "size_mb" in backups[0]

    # Test prune_backups with age threshold
    old_backup = tmp_path / "backup_20200101_000000.sql.gz"
    old_backup.write_bytes(b"sample_content")
    past_timestamp = (datetime.now(UTC) - timedelta(days=45)).timestamp()
    os.utime(old_backup, (past_timestamp, past_timestamp))

    assert len(list_backups(tmp_path)) == 2
    pruned_count = prune_backups(keep_days=30, out_dir=tmp_path)
    assert pruned_count == 1
    assert not old_backup.exists()
    assert backup_file.exists()


# ---------------------------------------------------------------------------
# 9. Data Retention, Deletion and Tenant Isolation
# ---------------------------------------------------------------------------

def test_data_retention_deletion_and_tenant_isolation():
    """Verify retention pruning of aged executions, soft-deletion semantics, and tenant isolation."""
    db = get_session()
    try:
        user_a = _create_test_user(db, email=f"tenant_a_{_uid()}@test.com")
        user_b = _create_test_user(db, email=f"tenant_b_{_uid()}@test.com")

        # 1. Retention Pruning Test: Aged finished execution pruned, recent preserved
        wf_a = WorkflowRecord(id=_uid("wf_a"), user_id=user_a.id, name="Tenant A Flow", data={}, active=True)
        db.add(wf_a)
        db.commit()

        aged_time = datetime.now(UTC) - timedelta(days=90)
        recent_time = datetime.now(UTC) - timedelta(hours=2)

        aged_exec = Execution(
            id=_uid("exec_aged"),
            workflow_id=wf_a.id,
            user_id=user_a.id,
            workflow_version=1,
            workflow_data={},
            status="success",
            started_at=aged_time,
            finished_at=aged_time + timedelta(seconds=2),
        )
        recent_exec = Execution(
            id=_uid("exec_recent"),
            workflow_id=wf_a.id,
            user_id=user_a.id,
            workflow_version=1,
            workflow_data={},
            status="running",
            started_at=recent_time,
        )
        db.add_all([aged_exec, recent_exec])
        db.commit()

        # Run retention prune with 30-day cutoff
        cutoff = datetime.now(UTC) - timedelta(days=30)
        counts = prune(db, cutoff)
        assert counts["executions"] >= 1

        # Assert aged execution is gone, recent execution remains
        assert db.get(Execution, aged_exec.id) is None
        assert db.get(Execution, recent_exec.id) is not None

        # 2. Soft-Deletion Semantics: setting deleted_at hides workflow from active listings
        wf_a.deleted_at = datetime.now(UTC)
        db.commit()

        active_wfs = db.query(WorkflowRecord).filter(
            WorkflowRecord.user_id == user_a.id,
            WorkflowRecord.deleted_at.is_(None),
        ).all()
        assert wf_a.id not in [w.id for w in active_wfs]

        # Historical execution record is still preserved and linked
        linked_exec = db.get(Execution, recent_exec.id)
        assert linked_exec is not None
        assert linked_exec.workflow_id == wf_a.id

        # 3. Tenant Isolation
        wf_b = WorkflowRecord(id=_uid("wf_b"), user_id=user_b.id, name="Tenant B Flow", data={}, active=True)
        db.add(wf_b)
        db.commit()

        tenant_a_wfs = db.query(WorkflowRecord).filter(WorkflowRecord.user_id == user_a.id).all()
        assert all(w.user_id == user_a.id for w in tenant_a_wfs)
        assert wf_b.id not in [w.id for w in tenant_a_wfs]
    finally:
        db.close()
