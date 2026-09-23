"""Live PostgreSQL integration tests (skipped when Postgres is down).

Run `docker compose up -d` from the repo root, then these run against
the real server: DDL, model CRUD, encrypted-credential round-trip and a
full engine execution. They prove the "production MUST use PostgreSQL"
path end to end.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy
from sqlalchemy import select, text

from app.config import get_settings
from app.db import Base, init_db
from app.engine.graph import build_graph, topological_sort, validate_graph
from app.models import Credential, WorkflowRecord
from app.schemas.workflow import Workflow

# Always use the test database — never the application DB.
from tests.conftest import TEST_DB_URL

POSTGRES_URL = TEST_DB_URL


def _pg_available() -> bool:
    try:
        eng = sqlalchemy.create_engine(POSTGRES_URL, connect_args={"connect_timeout": 2})
        with eng.connect():
            return True
    except Exception:
        return False


@pytest.fixture
def pg_session():
    if not _pg_available():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_URL} (docker compose up -d)")
    init_db(POSTGRES_URL)
    from app.db import get_session
    from app.models import User

    session = get_session()
    # Use TRUNCATE CASCADE (not DELETE) to avoid FK violations.
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.tables.values())
    session.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    session.commit()
    session.close()

    # Re-create the user needed by these tests.
    session = get_session()
    session.add(User(id=1, email="pg-demo@example.com", password_hash="not-used"))
    session.commit()

    yield session
    session.close()


def test_postgres_ddl_and_workflow_crud(pg_session) -> None:
    rec = WorkflowRecord(
        id="pg_wf_1",
        user_id=1,
        name="PG Workflow",
        description="",
        version=1,
        data={"id": "pg_wf_1", "name": "PG Workflow", "version": 1, "status": "draft",
              "nodes": [], "connections": [], "settings": {}},
    )
    pg_session.add(rec)
    pg_session.commit()
    loaded = pg_session.get(WorkflowRecord, "pg_wf_1")
    assert loaded is not None
    assert loaded.name == "PG Workflow"

    loaded.version = 2
    pg_session.commit()
    assert pg_session.get(WorkflowRecord, "pg_wf_1").version == 2
    pg_session.delete(loaded)
    pg_session.commit()
    assert pg_session.get(WorkflowRecord, "pg_wf_1") is None


def test_postgres_credential_roundtrip(pg_session) -> None:
    from app.security.crypto import decrypt_text, encrypt_text

    blob = encrypt_text('{"access_token": "secret-token-123", "refresh_token": "rt-456"}')
    assert b"secret-token-123" not in blob
    assert blob.startswith(b"v2:k0:") or blob.startswith(b"k0:gAAAA")  # AES-256-GCM v2 or Fernet at rest

    cred = Credential(
        id="pg_cred_1",
        user_id=1,
        name="PG Cred",
        type="salesforce",
        data=blob,
    )
    pg_session.add(cred)
    pg_session.commit()

    loaded = pg_session.get(Credential, "pg_cred_1")
    assert loaded is not None
    assert "secret-token-123" not in loaded.data.decode(errors="replace")
    assert "secret-token-123" in decrypt_text(loaded.data)


def test_postgres_engine_execution(pg_session) -> None:
    """A real workflow (manual -> set_data) executes against Postgres
    using the DB queue backend."""
    import asyncio
    from app.execution_runtime import run_job
    from app.models import Execution
    from app.queue import QueueJob, reset_queue

    doc = {
        "id": "pg_exec_wf",
        "name": "PG Exec",
        "version": 1,
        "status": "draft",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "parameters": {}},
            {"id": "s", "type": "set_data", "parameters": {"mode": "merge", "fields": {"who": "pg"}}},
        ],
        "connections": [{"source": "t", "target": "s"}],
        "settings": {},
    }
    workflow = Workflow.model_validate(doc)
    validate_graph(workflow)
    order = topological_sort(build_graph(workflow))
    assert order == ["t", "s"]

    pg_session.add(WorkflowRecord(
        id="pg_exec_wf",
        user_id=1,
        name="PG Exec",
        description="",
        version=1,
        active=False,
        data=doc,
    ))
    pg_session.commit()

    pg_session.add(Execution(
        id="exec_pg1",
        workflow_id="pg_exec_wf",
        user_id=1,
        workflow_version=1,
        workflow_data=doc,
        trigger="manual",
        status="running",
    ))
    pg_session.commit()

    events: list[dict] = []
    job = QueueJob(id="job_pg1", execution_id="exec_pg1",
                  payload={"workflow_id": "pg_exec_wf", "user_id": 1, "trigger": "manual",
                           "version": 1, "workflow_data": doc, "trigger_items": []})
    status = asyncio.run(run_job(job, events.append))
    assert status == "success"
    assert any(e.get("event") == "execution.completed" for e in events)

    pg_session.refresh  # no-op for clarity
    exec_row = pg_session.get(Execution, "exec_pg1")
    assert exec_row is not None
    assert exec_row.status == "success", exec_row.error
    assert exec_row.results is not None
    outputs = (exec_row.results or {}).get("outputs") or {}
    assert any(
        item.get("who") == "pg"
        for node_out in outputs.values()
        for item in (node_out.get("main") or [])
    )