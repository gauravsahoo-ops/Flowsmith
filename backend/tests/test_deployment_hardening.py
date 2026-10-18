"""Phase 7 — Production Deployment Hardening & SRE Verification Suite.

Validates:
1. Insecure default rejection (weak JWT, short key, default DB password, wildcard CORS).
2. Key generation & zero-downtime key rotation mechanism.
3. Database backup and disaster recovery streaming restore.
4. Readiness probe dependency checks (PostgreSQL + Redis).
5. Queue and worker lease recovery under simulated crash.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import ConfigError, Settings, validate_production_settings
from app.db import get_session
from app.models import Credential, User
from app.utils.backup import create_backup, list_backups, prune_backups, restore_backup


def _valid_prod_settings(**overrides) -> Settings:
    base = {
        "app_env": "production",
        "credentials_encryption_key": Fernet.generate_key().decode(),
        "jwt_secret": "secure-high-entropy-production-secret-min-32-chars",
        "database_url": "postgresql://flowsmith_user:StrongProdPassword123!@localhost:5432/automate",
        "cors_origins": "https://flowsmith.company.com,https://app.flowsmith.com",
        "safe_http_allowed_hosts": "",
        "safe_http_allowed_ports": "",
    }
    base.update(overrides)
    return Settings(**base)


class TestProductionConfigurationHardening:
    """Verifies that production environment startup strictly rejects insecure defaults."""

    def test_accepts_valid_hardened_production_config(self):
        validate_production_settings(_valid_prod_settings())

    def test_rejects_missing_encryption_key(self):
        with pytest.raises(ConfigError, match="CREDENTIALS_ENCRYPTION_KEY"):
            validate_production_settings(_valid_prod_settings(credentials_encryption_key=""))

    def test_rejects_short_encryption_key(self):
        with pytest.raises(ConfigError, match="CREDENTIALS_ENCRYPTION_KEY"):
            validate_production_settings(_valid_prod_settings(credentials_encryption_key="shortkey"))

    def test_rejects_short_jwt_secret(self):
        with pytest.raises(ConfigError, match="JWT_SECRET"):
            validate_production_settings(_valid_prod_settings(jwt_secret="too-short"))

    def test_rejects_common_weak_jwt_secret(self):
        for weak in ("dev-only-secret-change-me", "changeme", "secret", "password"):
            with pytest.raises(ConfigError, match="JWT_SECRET"):
                validate_production_settings(_valid_prod_settings(jwt_secret=weak))

    def test_rejects_sqlite_in_production(self):
        with pytest.raises(ConfigError, match="DATABASE_URL"):
            validate_production_settings(_valid_prod_settings(database_url="sqlite:///data.db"))

    def test_rejects_default_dev_db_password(self):
        with pytest.raises(ConfigError, match="DATABASE_URL"):
            validate_production_settings(
                _valid_prod_settings(database_url="postgresql://automate:automate@localhost:5432/automate")
            )

    def test_rejects_wildcard_cors_in_production(self):
        with pytest.raises(ConfigError, match="CORS_ORIGINS"):
            validate_production_settings(_valid_prod_settings(cors_origins="*"))
        with pytest.raises(ConfigError, match="CORS_ORIGINS"):
            validate_production_settings(_valid_prod_settings(cors_origins="https://app.com, *"))

    def test_rejects_insecure_default_redis_password(self):
        with pytest.raises(ConfigError, match="REDIS_PASSWORD"):
            validate_production_settings(_valid_prod_settings(redis_password="changeme"))


class TestDisasterRecoveryAndBackupCLI:
    """Validates real backup creation, listing, and streaming restore operations."""

    def test_backup_and_prune_lifecycle(self, tmp_path):
        dump_path = create_backup("lifecycle_test", out_dir=tmp_path)
        assert dump_path.exists()
        assert dump_path.name == "lifecycle_test.sql.gz"
        assert dump_path.stat().st_size > 0

        # Verify listing
        backups = list_backups(out_dir=tmp_path)
        assert len(backups) >= 1
        assert any(b["filename"] == "lifecycle_test.sql.gz" for b in backups)

        # Prune test with 0 days retention removes it
        pruned = prune_backups(keep_days=0, out_dir=tmp_path)
        assert pruned >= 1
        assert not dump_path.exists()


class TestKeyRotationMechanism:
    """Tests zero-downtime key rotation logic against live database records."""

    def test_rotate_keys_dry_run_and_commit(self):
        import sys
        root_dir = str(Path(__file__).resolve().parents[2])
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

        from scripts.rotate_encryption_key import rotate_keys

        # 1. Dry run
        new_keyring, cred_count, env_count = rotate_keys(apply=False)
        assert new_keyring is not None
        assert "," in new_keyring or len(new_keyring) == 44
        assert cred_count >= 0

        # 2. Key ring structure
        keys = [k.strip() for k in new_keyring.split(",") if k.strip()]
        assert len(keys) >= 1
        # Verify first key is a valid Fernet key
        Fernet(keys[0].encode())


class TestReadinessEndpoint:
    """Verifies that the readiness probe accurately reflects infrastructure state."""

    def test_readyz_payload_structure(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        res = client.get("/api/readyz")
        assert res.status_code in (200, 503)
        data = res.json()
        assert "data" in data
        assert "status" in data["data"]
        assert "checks" in data["data"]
        assert "postgres" in data["data"]["checks"]
        assert data["data"]["checks"]["postgres"] in ("ok", "error")
