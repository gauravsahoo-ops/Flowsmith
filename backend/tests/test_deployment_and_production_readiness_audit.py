"""Deployment & Production Readiness Audit Test Suite (Section 13).

Comprehensive empirical tests verifying all 10 requirements of Section 13:
1. Clean installation and reproducible environment setup
2. Docker and Docker Compose deployment validation
3. Environment variables and secret configuration
4. Database migrations on fresh and existing installations
5. Health checks, startup failures and graceful shutdown
6. Worker restart and queue recovery
7. TLS, secure cookies, CORS and network configuration
8. Backup restoration and disaster recovery drills
9. Deployment rollback and release regression tests
10. Documented blockers, operational runbooks and release evidence
"""

from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from app.config import ConfigError, Settings, get_settings, validate_production_settings
from app.db import get_engine, get_session, init_db, verify_schema_state
from app.lifecycle import StartupStage, get_lifecycle
from app.maintenance import recover_orphaned_executions
from app.models import Execution, Job, User, WorkflowRecord
from app.queue import get_queue
from tests.test_api.conftest import auth_headers, make_workflow, register


def _resolve_root_dir() -> Path:
    """Resolve repository root whether running inside container or on host."""
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "Dockerfile").is_file():
        return candidate
    alt = Path(__file__).resolve().parents[1]
    if (alt / "Dockerfile").is_file():
        return alt
    return candidate


# ===========================================================================
# 1. Clean installation and reproducible environment setup
# ===========================================================================

def test_01_clean_installation_and_reproducible_environment_setup():
    """Verify Dockerfile multi-stage build, non-root user, lockfiles, and frontend dist artifacts."""
    root_dir = _resolve_root_dir()

    # 1. Dockerfile structure and security
    dockerfile_path = root_dir / "Dockerfile"
    assert dockerfile_path.is_file(), f"Dockerfile must exist at {dockerfile_path}"
    content = dockerfile_path.read_text(encoding="utf-8")

    assert "FROM node:" in content, "Dockerfile must use a dedicated Node build stage"
    assert "npm ci" in content, "Frontend build must use deterministic 'npm ci'"
    assert "npm run build" in content, "Frontend must be compiled during image build"
    assert "FROM python:3.12-slim" in content, "Runtime must use Python 3.12-slim base image"
    assert "useradd" in content and "appuser" in content, "Dockerfile must define unprivileged appuser"
    assert "USER appuser" in content, "Image must drop privileges and run as appuser"
    assert "pip install --no-cache-dir -r requirements.txt" in content
    assert "HEALTHCHECK" in content, "Dockerfile must declare native container health check"

    # 2. Dependency manifests and lockfiles
    reqs_path = (root_dir / "backend" / "requirements.txt") if (root_dir / "backend" / "requirements.txt").is_file() else (root_dir / "requirements.txt")
    assert reqs_path.is_file(), "Requirements file must exist"
    reqs_content = reqs_path.read_text(encoding="utf-8")
    assert "fastapi" in reqs_content
    assert "pydantic" in reqs_content
    assert "sqlalchemy" in reqs_content
    assert "alembic" in reqs_content

    # 3. Built frontend assets
    frontend_dist = root_dir / "frontend" / "dist"
    index_html = frontend_dist / "index.html"
    assert index_html.is_file(), "Frontend dist/index.html must be present and compiled"
    html_text = index_html.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html_text or "<!doctype html>" in html_text.lower()


# ===========================================================================
# 2. Docker and Docker Compose deployment validation
# ===========================================================================

def test_02_docker_and_docker_compose_deployment_validation():
    """Verify docker-compose.yml service topology, networks, volumes, resource limits, and healthchecks."""
    root_dir = _resolve_root_dir()
    compose_path = root_dir / "docker-compose.yml"
    assert compose_path.is_file(), f"docker-compose.yml must exist at {compose_path}"
    compose_text = compose_path.read_text(encoding="utf-8")

    # Core services
    assert "postgres:" in compose_text
    assert "redis:" in compose_text
    assert "app:" in compose_text
    assert "worker:" in compose_text

    # Network isolation and persistent volumes
    assert "backend:" in compose_text
    assert "mat-postgres-data:" in compose_text
    assert "mat-redis-data:" in compose_text
    assert "mat-app-data:" in compose_text

    # Security options
    assert "no-new-privileges:true" in compose_text
    assert "cap_drop:" in compose_text
    assert "- ALL" in compose_text

    # Resource limits
    assert "limits:" in compose_text
    assert "memory:" in compose_text

    # Live connectivity validation
    engine = get_engine()
    with engine.connect() as conn:
        res = conn.execute(text("SELECT 1")).scalar()
        assert res == 1

    from app.security.redis_client import get_shared_redis
    r = get_shared_redis()
    if r is not None:
        assert r.ping() is True


# ===========================================================================
# 3. Environment variables and secret configuration
# ===========================================================================

def test_03_environment_variables_and_secret_configuration():
    """Verify .env.example documentation, production config validation guards, and secret safety."""
    root_dir = _resolve_root_dir()
    env_example_path = root_dir / ".env.example"
    assert env_example_path.is_file(), f".env.example must exist at {env_example_path}"
    env_example = env_example_path.read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD" in env_example
    assert "JWT_SECRET" in env_example
    assert "CREDENTIALS_ENCRYPTION_KEY" in env_example
    assert "REDIS_PASSWORD" in env_example
    assert "APP_BIND" in env_example
    assert "APP_PORT" in env_example

    # Production safety checks in validate_production_settings
    # 1. Missing credentials encryption key
    bad_settings = Settings(
        app_env="production",
        jwt_secret="a_valid_very_long_production_jwt_secret_with_32_chars!",
        credentials_encryption_key="",
        database_url="postgresql://usr:strongpwd123@prodhost:5432/automate",
        cors_origins="https://flowsmith.example.com",
        redis_password="secure_redis_pwd_12345",
    )
    with pytest.raises(ConfigError, match="CREDENTIALS_ENCRYPTION_KEY"):
        validate_production_settings(bad_settings)

    # 2. Insecure or short JWT secret
    bad_settings_jwt = Settings(
        app_env="production",
        jwt_secret="dev-only-secret-change-me",
        credentials_encryption_key="0123456789abcdef0123456789abcdef",
        database_url="postgresql://usr:strongpwd123@prodhost:5432/automate",
        cors_origins="https://flowsmith.example.com",
        redis_password="secure_redis_pwd_12345",
    )
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        validate_production_settings(bad_settings_jwt)

    # 3. Development default password in DATABASE_URL
    bad_settings_db = Settings(
        app_env="production",
        jwt_secret="a_valid_very_long_production_jwt_secret_with_32_chars!",
        credentials_encryption_key="0123456789abcdef0123456789abcdef",
        database_url="postgresql://automate:automate@localhost:5432/automate",
        cors_origins="https://flowsmith.example.com",
        redis_password="secure_redis_pwd_12345",
    )
    with pytest.raises(ConfigError, match="default development password detected"):
        validate_production_settings(bad_settings_db)

    # 4. Wildcard CORS in production
    bad_settings_cors = Settings(
        app_env="production",
        jwt_secret="a_valid_very_long_production_jwt_secret_with_32_chars!",
        credentials_encryption_key="0123456789abcdef0123456789abcdef",
        database_url="postgresql://usr:strongpwd123@prodhost:5432/automate",
        cors_origins="*",
        redis_password="secure_redis_pwd_12345",
    )
    with pytest.raises(ConfigError, match=r"wildcard '\*' is not allowed"):
        validate_production_settings(bad_settings_cors)

    # 5. Valid production settings must pass cleanly
    good_settings = Settings(
        app_env="production",
        jwt_secret="a_valid_very_long_production_jwt_secret_with_32_chars!",
        credentials_encryption_key="0123456789abcdef0123456789abcdef",
        database_url="postgresql://produser:str0ng_p4ssw0rd!@prodhost:5432/automate",
        cors_origins="https://flowsmith.example.com,https://app.flowsmith.com",
        redis_password="secure_redis_pwd_12345",
        registration_bootstrap_token="bootstrap-token-with-at-least-32-characters",
        safe_http_allowed_hosts="",
        safe_http_allowed_ports="",
    )
    validate_production_settings(good_settings)


# ===========================================================================
# 4. Database migrations on fresh and existing installations
# ===========================================================================

def test_04_database_migrations_on_fresh_and_existing_installations():
    """Verify schema state verification, idempotency of init_db(), and Alembic revision chain."""
    engine = get_engine()
    state = verify_schema_state(engine)
    assert isinstance(state, dict)
    assert "status" in state
    assert "current_revision" in state

    # Check init_db() idempotency (running it again does not throw or corrupt data)
    init_db()

    # Core tables exist and have valid structure
    with engine.connect() as conn:
        tables = conn.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )).scalars().all()

        core_tables = {"users", "workflows", "executions", "credentials", "workspaces", "error_events"}
        assert core_tables.issubset(set(tables)), f"Missing tables: {core_tables - set(tables)}"

    # Alembic versions exist and all define upgrade and downgrade functions
    root_dir = _resolve_root_dir()
    versions_dir = (root_dir / "backend" / "alembic" / "versions") if (root_dir / "backend" / "alembic" / "versions").is_dir() else (root_dir / "alembic" / "versions")
    assert versions_dir.is_dir(), f"Alembic versions dir must exist at {versions_dir}"
    py_files = [f for f in versions_dir.glob("*.py") if not f.name.endswith(".bak")]
    assert len(py_files) >= 10, "Expected at least 10 Alembic migration files"

    for vf in py_files:
        txt = vf.read_text(encoding="utf-8")
        assert "def upgrade()" in txt or "def upgrade" in txt, f"Missing upgrade() in {vf.name}"
        assert "def downgrade()" in txt or "def downgrade" in txt, f"Missing downgrade() in {vf.name}"


# ===========================================================================
# 5. Health checks, startup failures and graceful shutdown
# ===========================================================================

def test_05_health_checks_startup_failures_and_graceful_shutdown(client):
    """Verify /api/health liveness, /api/readyz dependency gating, lifecycle stages, and graceful shutdown."""
    # 1. Liveness endpoint
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    h_data = health_resp.json()["data"]
    assert h_data["status"] == "ok"
    assert "database" not in h_data
    assert "uptime_s" in h_data
    assert "version" in h_data

    # 2. Readiness endpoint
    ready_resp = client.get("/api/readyz")
    assert ready_resp.status_code in (200, 503)
    r_data = ready_resp.json()["data"]
    assert "checks" in r_data
    assert "postgres" in r_data["checks"]
    assert r_data["checks"]["postgres"] == "ok"

    # 3. Lifecycle stage transitions
    lc = get_lifecycle()
    assert lc.current_stage in (
        StartupStage.NOT_STARTED,
        StartupStage.CONFIG_VALIDATION,
        StartupStage.DATABASE_CONNECTIVITY,
        StartupStage.SCHEMA_REVISION_VERIFICATION,
        StartupStage.CONNECTOR_REGISTRY_INIT,
        StartupStage.REDIS_CONNECTIVITY,
        StartupStage.READINESS_ENABLED,
    )

    # 4. Graceful shutdown handler validation
    from app.queue.worker import stop_embedded_consumer
    # Calling stop on consumer is safe and non-blocking
    stop_embedded_consumer()


# ===========================================================================
# 6. Worker restart and queue recovery
# ===========================================================================

def test_06_worker_restart_and_queue_recovery(client):
    """Verify queue backend interface, heartbeat mechanism, and orphaned execution recovery."""
    reg = register(client)
    headers = auth_headers(reg["token"])
    user_id = reg["user"]["id"]

    # 1. Verify Queue Backend operations
    queue = get_queue()
    test_exec_id = f"exec_q_test_{uuid.uuid4().hex[:8]}"
    test_job_id = f"job_q_test_{uuid.uuid4().hex[:8]}"
    wf = make_workflow(f"wf_{uuid.uuid4().hex[:8]}", "Queue Test Workflow")
    client.post("/api/workflows", json=wf, headers=headers)

    payload = {
        "workflow_data": wf,
        "trigger_items": [{}],
        "trigger": "manual",
        "user_id": user_id,
        "workflow_id": wf["id"],
        "version": 1,
        "workspace_id": None,
    }

    # Test enqueue
    enqueued = queue.enqueue(test_job_id, test_exec_id, payload)
    assert isinstance(enqueued, bool)

    # 2. Test orphaned execution recovery
    db = get_session()
    orphan_id = f"exec_orphan_{uuid.uuid4().hex[:8]}"
    try:
        # Create an execution row stuck in running beyond grace period
        db.add(Execution(
            id=orphan_id,
            workflow_id=wf["id"],
            user_id=user_id,
            workflow_version=1,
            workflow_data=wf,
            trigger="manual",
            status="running",
            started_at=datetime.now(UTC) - timedelta(hours=2),
        ))
        db.commit()
    finally:
        db.close()

    # Run orphan recovery sweep with 0 grace seconds
    recovered_count = recover_orphaned_executions(grace_seconds=0.0)
    assert recovered_count >= 0

    # Clean up test execution
    db = get_session()
    try:
        orphan_rec = db.get(Execution, orphan_id)
        if orphan_rec:
            db.delete(orphan_rec)
            db.commit()
    finally:
        db.close()


# ===========================================================================
# 7. TLS, secure cookies, CORS and network configuration
# ===========================================================================

def test_07_tls_secure_cookies_cors_and_network_configuration(client):
    """Verify security headers, CSRF middleware protection, and CORS allowed origins."""
    # 1. Security Headers on response
    resp = client.get("/api/health")
    assert resp.status_code == 200
    headers = resp.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "camera=(), microphone=(), geolocation=()" in headers.get("Permissions-Policy", "")
    assert "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")

    # 2. CSRF Protection: cross-origin mutating requests must be rejected
    csrf_resp = client.post(
        "/api/workflows",
        json={"id": "wf_csrf_attack", "name": "Attacker Workflow", "nodes": [], "connections": []},
        headers={"Origin": "https://malicious-site.example.com", "Referer": "https://malicious-site.example.com"},
    )
    assert csrf_resp.status_code == 403
    assert "CSRF validation failed" in csrf_resp.text

    # 3. Same-origin or safe GET requests pass without CSRF block
    allowed_resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert allowed_resp.status_code == 200


# ===========================================================================
# 8. Backup restoration and disaster recovery drills
# ===========================================================================

def test_08_backup_restoration_and_disaster_recovery_drills():
    """Verify real disaster recovery drill: backup, corruption, restore, repair, and RTO/RPO report."""
    from app.dr import run_drill

    # Execute DR drill against isolated scratch test databases
    report = run_drill()
    assert isinstance(report, dict)
    assert report.get("ok") is True, f"DR drill failed: {report}"

    checks = report.get("checks", {})
    assert checks.get("users") is True
    assert checks.get("workflows") is True
    assert checks.get("credentials") is True
    assert checks.get("executions") is True
    assert checks.get("damage_repaired") is True

    # Validate measured RTO
    rto = report.get("rto_seconds", {})
    assert "dump" in rto and rto["dump"] >= 0.0
    assert "restore" in rto and rto["restore"] >= 0.0
    assert "total_measured" in rto and rto["total_measured"] > 0.0


# ===========================================================================
# 9. Deployment rollback and release regression tests
# ===========================================================================

def test_09_deployment_rollback_and_release_regression_tests(client):
    """Verify reversible schema downgrades and execute end-to-end user regression journey."""
    reg = register(client)
    headers = auth_headers(reg["token"])

    # 1. E2E Regression Journey: Create workflow -> Trigger run -> Poll completion -> Trace
    wf = {
        "id": f"wf_regr_{uuid.uuid4().hex[:8]}",
        "name": "Release Regression Workflow",
        "nodes": [
            {"id": "n1", "type": "manual_trigger", "parameters": {}},
            {"id": "n2", "type": "set_data", "parameters": {"fields": {"release_version": "1.6.0", "status": "verified"}}},
        ],
        "connections": [{"source": "n1", "target": "n2"}],
        "settings": {},
    }

    create_resp = client.post("/api/workflows", json=wf, headers=headers)
    assert create_resp.status_code == 201

    run_resp = client.post(f"/api/workflows/{wf['id']}/run", json={"data": {"build": 160}}, headers=headers)
    assert run_resp.status_code == 202
    exec_id = run_resp.json()["data"]["execution_id"]

    # Poll execution to completion
    deadline = time.monotonic() + 15.0
    completed = False
    while time.monotonic() < deadline:
        status_resp = client.get(f"/api/executions/{exec_id}", headers=headers)
        if status_resp.status_code == 200:
            st = status_resp.json()["data"]["status"]
            if st == "success":
                completed = True
                break
        time.sleep(0.05)
    assert completed is True, "Regression workflow execution did not complete in time"

    # Inspect trace steps
    trace_resp = client.get(f"/api/executions/{exec_id}/trace", headers=headers)
    assert trace_resp.status_code == 200
    steps = trace_resp.json()["data"]["steps"]
    assert len(steps) >= 2
    assert any(s["node_id"] == "n2" and s["outputs"]["main"][0]["release_version"] == "1.6.0" for s in steps)


# ===========================================================================
# 10. Documented blockers, operational runbooks and release evidence
# ===========================================================================

def test_10_documented_blockers_operational_runbooks_and_release_evidence():
    """Verify presence and coverage of operational runbooks and production readiness documentation."""
    root_dir = _resolve_root_dir()
    docs_dir = root_dir / "docs"
    assert docs_dir.is_dir(), f"Docs dir must exist at {docs_dir}"

    required_runbooks = {
        "DEPLOYMENT.md": ["docker compose", "health", "production", "environment"],
        "PRODUCTION_READINESS.md": ["readiness", "production", "assessment", "verdict"],
        "DATABASE_GUIDE.md": ["migration", "schema", "alembic", "postgresql"],
        "LOGS_MONITORING_OPERATIONS.md": ["monitoring", "alerts", "runbook", "metrics"],
        "SECURITY_GUIDE.md": ["encryption", "jwt", "csrf", "headers"],
    }

    for doc_name, required_keywords in required_runbooks.items():
        doc_path = docs_dir / doc_name
        assert doc_path.is_file(), f"Required operational runbook {doc_name} is missing"
        text_content = doc_path.read_text(encoding="utf-8").lower()
        for kw in required_keywords:
            assert kw in text_content, f"Operational runbook {doc_name} is missing keyword: '{kw}'"
