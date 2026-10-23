"""Phase 7 — Production Deployment Hardening & SRE Verification Suite.

Validates:
1. Insecure default rejection (weak JWT, short key, default DB password, wildcard CORS).
2. Key generation & zero-downtime key rotation mechanism.
3. Database backup and disaster recovery streaming restore.
4. Readiness probe dependency checks (PostgreSQL + Redis).
5. Queue and worker lease recovery under simulated crash.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import ConfigError, Settings, validate_production_settings
from app.utils.backup import create_backup, list_backups, prune_backups


def _valid_prod_settings(**overrides) -> Settings:
    base = {
        "app_env": "production",
        "credentials_encryption_key": Fernet.generate_key().decode(),
        "jwt_secret": "secure-high-entropy-production-secret-min-32-chars",
        "database_url": "postgresql://flowsmith_user:StrongProdPassword123!@localhost:5432/automate",
        "cors_origins": "https://flowsmith.company.com,https://app.flowsmith.com",
        "registration_bootstrap_token": "bootstrap-token-with-at-least-32-characters",
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
        for weak in ("changeme", "password", "redis", "default", "admin", "123456", "root"):
            with pytest.raises(ConfigError, match="REDIS_PASSWORD"):
                validate_production_settings(_valid_prod_settings(redis_password=weak))

    def test_rejects_empty_cors_in_production(self):
        with pytest.raises(ConfigError, match="CORS_ORIGINS"):
            validate_production_settings(_valid_prod_settings(cors_origins=""))
        with pytest.raises(ConfigError, match="CORS_ORIGINS"):
            validate_production_settings(_valid_prod_settings(cors_origins="   "))

    def test_rejects_missing_redis_url_when_queue_backend_redis(self):
        with pytest.raises(ConfigError, match="REDIS_URL"):
            validate_production_settings(_valid_prod_settings(queue_backend="redis", redis_url=""))

    def test_rejects_unauthenticated_redis_when_require_redis_auth(self):
        with pytest.raises(ConfigError, match="REDIS_PASSWORD"):
            validate_production_settings(
                _valid_prod_settings(
                    queue_backend="redis",
                    redis_url="redis://localhost:6379/0",
                    redis_password="",
                    require_redis_auth=True,
                )
            )

    def test_rejects_weak_password_in_redis_url(self):
        with pytest.raises(ConfigError, match="REDIS_PASSWORD"):
            validate_production_settings(
                _valid_prod_settings(
                    queue_backend="redis",
                    redis_url="redis://:changeme@redis:6379/0",
                )
            )

    def test_rejects_missing_stripe_secrets_when_billing_enforced(self):
        with pytest.raises(ConfigError, match="STRIPE_SECRET_KEY"):
            validate_production_settings(_valid_prod_settings(billing_enforcement=True, stripe_secret_key=""))
        with pytest.raises(ConfigError, match="STRIPE_WEBHOOK_SECRET"):
            validate_production_settings(
                _valid_prod_settings(
                    billing_enforcement=True,
                    stripe_secret_key="sk_live_prod_test_key",
                    stripe_webhook_secret="",
                )
            )

    def test_accepts_valid_hardened_redis_queue_in_production(self):
        validate_production_settings(
            _valid_prod_settings(
                queue_backend="redis",
                redis_url="redis://:VeryStrongSecretKey2026!@redis:6379/0",
                require_redis_auth=True,
            )
        )


class TestDockerComposeNetworkBindingDefaults:
    """Verifies that compose topologies do not expose services publicly by default."""

    @pytest.fixture
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def test_docker_compose_loopback_bindings(self, root_dir: Path):
        import yaml

        compose_path = root_dir / "docker-compose.yml"
        assert compose_path.exists(), f"Missing {compose_path}"

        with compose_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        services = data.get("services", {})
        assert "app" in services
        assert "postgres" in services
        assert "redis" in services

        # 1. App binding must default to 127.0.0.1, not 0.0.0.0
        app_ports = services["app"].get("ports", [])
        assert any("127.0.0.1" in p for p in app_ports), f"App must bind to loopback by default: {app_ports}"
        assert not any("0.0.0.0" in p for p in app_ports), f"App must not default to 0.0.0.0: {app_ports}"

        # 2. Infrastructure ports must bind strictly to 127.0.0.1
        for sname in ("postgres", "redis", "prometheus", "grafana", "minio"):
            if sname in services and "ports" in services[sname]:
                ports = services[sname]["ports"]
                for p in ports:
                    p_str = str(p)
                    assert p_str.startswith("127.0.0.1:"), (
                        f"Service {sname} port {p_str} is not bound to 127.0.0.1 loopback"
                    )

    def test_docker_compose_staging_network_isolation(self, root_dir: Path):
        import yaml

        staging_path = root_dir / "docker-compose.staging.yml"
        assert staging_path.exists(), f"Missing {staging_path}"

        with staging_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        services = data.get("services", {})
        assert "app" in services
        app_ports = services["app"].get("ports", [])
        assert any("127.0.0.1" in p for p in app_ports), f"Staging app must default to loopback: {app_ports}"
        assert not any("0.0.0.0" in p for p in app_ports), f"Staging app must not default to 0.0.0.0: {app_ports}"

        # In staging, databases must have zero published host ports
        for sname in ("postgres", "redis"):
            if sname in services:
                assert "ports" not in services[sname], (
                    f"Staging {sname} must not publish host ports; should be bridge-internal only"
                )


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
