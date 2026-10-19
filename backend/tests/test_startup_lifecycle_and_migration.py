"""Empirical test suite for Flowsmith backend startup, migrations, registry & production stability.

Covers:
1. Migration advisory locking, schema verification, and idempotent skip.
2. Migration CLI runner with check-only mode.
3. Lifecycle state machine: 8 formal stages, duration tracking, process metadata, failure reporting.
4. Connector registry: allow_idempotent, diagnostics tracking, concurrency safety.
5. Liveness probe (/api/health): pure process health decoupled from downstream DB outages.
6. Readiness probe (/readyz, /api/readyz): 503 gating until readiness stage and schema verification.
7. Rate limiting: anonymous IP fallback, auth route protection, skip paths.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.connectors import ConnectorCategory, ConnectorDefinitionV1, ConnectorLifecycle, ConnectorSDK
from app.connectors.registry import ConnectorRegistry
from app.db import (
    EXPECTED_ALEMBIC_HEAD,
    FLOWSMITH_MIGRATION_LOCK_ID,
    get_current_revision,
    verify_schema_state,
    _run_alembic_upgrade,
)
from app.lifecycle import LifecycleManager, StartupStage, get_lifecycle
from app.main import app as main_app
from app.middleware.rate_limit import RateLimitMiddleware, _SKIP_PATHS
from app.db import Base


# ==============================================================================
# 1. Database Migrations, Advisory Locking & Schema Drift
# ==============================================================================


def test_migration_advisory_locking_and_idempotent_skip():
    """Verify advisory locking and idempotent skip when schema is at head."""
    mock_conn = MagicMock()
    mock_inspector = MagicMock()
    mock_inspector.has_table.return_value = True

    # 1. Test idempotent skip when current revision matches EXPECTED_ALEMBIC_HEAD
    with patch("app.db.get_current_revision", return_value=EXPECTED_ALEMBIC_HEAD), patch(
        "alembic.command.upgrade"
    ) as mock_upgrade:
        _run_alembic_upgrade()
        mock_upgrade.assert_not_called()

    # 2. Test migration execution under advisory lock when revision is behind
    with patch("app.db.get_current_revision", side_effect=["a9b8c7d6e5f4", EXPECTED_ALEMBIC_HEAD]), patch(
        "app.db.engine.dialect.name", "postgresql"
    ), patch("app.db.engine.connect", return_value=mock_conn), patch(
        "app.db.inspect", return_value=mock_inspector
    ), patch(
        "alembic.command.upgrade"
    ) as mock_upgrade:
        _run_alembic_upgrade()
        mock_upgrade.assert_called_once()

        # Check pg_advisory_lock was requested
        executed_sqls = [str(call[0][0]) for call in mock_conn.execute.call_args_list if call[0]]
        assert any(str(FLOWSMITH_MIGRATION_LOCK_ID) in sql for sql in executed_sqls)


def test_verify_schema_state():
    """Verify schema state detection identifies matched revisions and drift."""
    mock_engine = MagicMock()

    # Matches expected (all Base tables present + alembic_version at head)
    with patch("app.db.get_current_revision", return_value=EXPECTED_ALEMBIC_HEAD), patch(
        "app.db.inspect"
    ) as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = list(Base.metadata.tables.keys()) + ["alembic_version"]
        mock_inspect.return_value = mock_inspector

        info = verify_schema_state(mock_engine)
        assert info["ok"] is True
        assert info["current_revision"] == EXPECTED_ALEMBIC_HEAD
        assert info["expected_revision"] == EXPECTED_ALEMBIC_HEAD
        assert info["status"] == "ok"

    # Drifted (missing tables and old revision)
    with patch("app.db.get_current_revision", return_value="outdated_rev_123"), patch(
        "app.db.inspect"
    ) as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = []
        mock_inspect.return_value = mock_inspector

        info = verify_schema_state(mock_engine)
        assert info["ok"] is False
        assert info["current_revision"] == "outdated_rev_123"
        assert info["expected_revision"] == EXPECTED_ALEMBIC_HEAD
        assert info["status"] == "drift_detected"


def test_migration_cli_check_only():
    """Verify migrate CLI exits cleanly with --check-only."""
    from app.scripts.migrate import main as cli_main

    with patch("app.db.get_current_revision", return_value=EXPECTED_ALEMBIC_HEAD), patch(
        "sys.argv", ["migrate.py", "--check-only"]
    ):
        exit_code = cli_main()
        assert exit_code == 0


# ==============================================================================
# 2. Lifecycle State Machine & Duration Tracking
# ==============================================================================


def test_lifecycle_state_machine_progression():
    """Verify state machine progression across all 8 stages with duration tracking."""
    lc = LifecycleManager(service_name="test-service")
    assert lc.current_stage == StartupStage.NOT_STARTED
    assert lc.is_ready is False
    assert lc.pid == os.getpid()

    expected_stages = [
        StartupStage.CONFIG_VALIDATION,
        StartupStage.DATABASE_CONNECTIVITY,
        StartupStage.SCHEMA_REVISION_VERIFICATION,
        StartupStage.CONNECTOR_REGISTRY_INIT,
        StartupStage.REDIS_CONNECTIVITY,
        StartupStage.SERVICE_INITIALIZATION,
        StartupStage.STARTUP_COMPLETE,
        StartupStage.READINESS_ENABLED,
    ]

    for stage in expected_stages:
        lc.transition_to(stage, f"Entering {stage.value}")
        assert lc.current_stage == stage

    assert lc.is_ready is True
    summary = lc.get_status_summary()
    assert summary["is_ready"] is True
    assert summary["stage"] == StartupStage.READINESS_ENABLED.value
    assert len(summary["history"]) == len(expected_stages)
    assert all("duration_s" in h for h in summary["history"])


def test_lifecycle_failure_transition():
    """Verify failure state transition and non-leaking diagnostic summary."""
    lc = LifecycleManager(service_name="test-service")
    lc.transition_to(StartupStage.DATABASE_CONNECTIVITY)
    lc.mark_failed(Exception("Database connection timeout at 10.0.0.1"), StartupStage.DATABASE_CONNECTIVITY)

    assert lc.is_failed is True
    assert lc.is_ready is False
    assert lc.current_stage == StartupStage.FAILED
    assert "Database connection timeout" in (lc.failure_reason or "")


# ==============================================================================
# 3. Connector Registry Idempotency & Diagnostics
# ==============================================================================


class _MockConnector(ConnectorSDK):
    connector_id = "mock_conn"
    display_name = "Mock Connector"
    description = "Mock"
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self, cid: str = "mock_conn", version: str = "1.0.0"):
        self.connector_id = cid
        self.version = version
        super().__init__(self.connector_id, self.display_name, self.description)

    @property
    def node_types(self) -> list[str]:
        return [f"{self.connector_id}_node"]

    def connect(self, credentials: dict) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def op_execute(self, operation: str, params: dict, context: dict) -> dict:
        return {"status": "ok"}


def _mock_definition(cid: str = "mock_conn", version: str = "1.0.0") -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=cid,
        display_name="Mock Connector",
        description="Mock",
        category="api",
        connector_version=version,
        lifecycle_status=ConnectorLifecycle.STABLE.value,
        operations={},
        triggers={},
        credential_types={},
    )


def test_connector_registry_idempotency_and_diagnostics():
    """Verify registry accepts allow_idempotent without re-wiping state."""
    registry = ConnectorRegistry()
    registry.initialize()

    conn1 = _MockConnector("conn_a", "1.0.0")
    defn1 = _mock_definition("conn_a", "1.0.0")

    # Initial registration
    registry.register(conn1, defn1)
    diag1 = registry.get_diagnostics()
    assert diag1["attempts"] == 1
    assert diag1["unique"] == 1
    assert diag1["duplicates"] == 0

    # Repeat registration with allow_idempotent=True
    registry.register(conn1, defn1, allow_idempotent=True)
    diag2 = registry.get_diagnostics()
    assert diag2["attempts"] == 2
    assert diag2["unique"] == 1
    assert diag2["duplicates"] == 1

    # Upgrade registration with newer version
    conn1_v2 = _MockConnector("conn_a", "2.0.0")
    defn1_v2 = _mock_definition("conn_a", "2.0.0")
    registry.register(conn1_v2, defn1_v2)
    diag3 = registry.get_diagnostics()
    assert diag3["upgrades"] == 1
    assert registry.get_definition("conn_a").connector_version == "2.0.0"


def test_register_builtin_connectors_idempotency():
    """Verify register_builtin_connectors is safe to call repeatedly."""
    from app.connectors import get_registry, register_builtin_connectors

    reg = get_registry()
    count_initial = len(reg.list_definitions())

    # Call register_builtin_connectors again
    register_builtin_connectors()
    count_after = len(reg.list_definitions())

    assert count_after >= count_initial
    assert count_after > 50  # Must contain built-ins


# ==============================================================================
# 4. Liveness Probe (/api/health)
# ==============================================================================


def test_health_liveness_decoupled_from_database():
    """Verify /api/health never queries database and returns 200 even if database fails."""
    client = TestClient(main_app)

    # Simulate database engine failure
    with patch("app.main.get_session", side_effect=Exception("Database unreachable")):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["status"] == "ok"
        assert "pid" in data
        assert "stage" in data
        assert "database" not in data  # No database query in pure liveness probe


# ==============================================================================
# 5. Readiness Probe (/readyz, /api/readyz)
# ==============================================================================


def test_readyz_gated_by_lifecycle_readiness():
    """Verify /readyz returns 503 before READINESS_ENABLED and 200 after."""
    client = TestClient(main_app)
    lc = get_lifecycle()

    try:
        # Case 1: Lifecycle is NOT ready -> 503
        lc.transition_to(StartupStage.CONFIG_VALIDATION)
        resp = client.get("/readyz")
        assert resp.status_code == 503
        data = resp.json()["data"]
        assert data["status"] == "not_ready"
        assert "checks" in data
        assert "lifecycle" in data["checks"]

        # Case 2: Lifecycle is ready and schema is aligned -> 200
        lc.transition_to(StartupStage.READINESS_ENABLED)
        with patch(
            "app.db.verify_schema_state",
            return_value={"ok": True, "status": "ok", "current_revision": EXPECTED_ALEMBIC_HEAD, "expected_revision": EXPECTED_ALEMBIC_HEAD},
        ), patch("app.db.engine.connect"):
            resp = client.get("/readyz")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["status"] == "ready"
            assert data["checks"]["postgres"] == "ok"
            assert "ok" in data["checks"]["schema"]
    finally:
        # Restore ready state
        lc.transition_to(StartupStage.READINESS_ENABLED)


def test_readyz_reports_503_on_schema_drift():
    """Verify /readyz returns 503 if schema drift is detected."""
    client = TestClient(main_app)
    lc = get_lifecycle()

    try:
        lc.transition_to(StartupStage.READINESS_ENABLED)
        with patch(
            "app.db.verify_schema_state",
            return_value={"ok": False, "status": "drift_detected", "current_revision": "old_rev", "expected_revision": EXPECTED_ALEMBIC_HEAD},
        ), patch("app.db.engine.connect"):
            resp = client.get("/readyz")
            assert resp.status_code == 503
            data = resp.json()["data"]
            assert data["status"] == "not_ready"
            assert "drift_detected" in data["checks"]["schema"]
    finally:
        lc.transition_to(StartupStage.READINESS_ENABLED)


# ==============================================================================
# 6. Rate Limiting Middleware Protection
# ==============================================================================


def test_rate_limit_skip_paths_includes_readiness():
    """Verify readiness and health probes are exempted from rate limiting."""
    assert "/readyz" in _SKIP_PATHS
    assert "/api/readyz" in _SKIP_PATHS
    assert "/api/health" in _SKIP_PATHS


def test_rate_limit_strict_auth_paths():
    """Verify sensitive auth paths enforce strict per-minute limits."""
    test_app = FastAPI()

    @test_app.post("/api/auth/login")
    async def login():
        return {"status": "ok"}

    from types import SimpleNamespace

    mock_settings = SimpleNamespace(
        rate_limit_enabled=True,
        rate_limit_per_minute=300,
        rate_limit_api_key_per_minute=600,
    )

    with patch("app.middleware.rate_limit.get_settings", return_value=mock_settings):
        test_app.add_middleware(RateLimitMiddleware, redis_client=None)
        client = TestClient(test_app)

        # 20 attempts allowed on auth routes, 21st must be 429
        for _ in range(20):
            res = client.post("/api/auth/login")
            assert res.status_code == 200

        res_limited = client.post("/api/auth/login")
        assert res_limited.status_code == 429
        assert res_limited.json()["error"] == "rate_limit_exceeded"
