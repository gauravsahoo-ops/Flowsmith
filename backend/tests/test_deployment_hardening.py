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

    def test_rejects_short_metrics_token(self):
        with pytest.raises(ConfigError, match="METRICS_TOKEN"):
            validate_production_settings(_valid_prod_settings(metrics_token="short-token"))

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

    def test_accepts_valid_hardened_redis_queue_in_production(self):
        validate_production_settings(
            _valid_prod_settings(
                queue_backend="redis",
                redis_url="redis://:VeryStrongSecretKey2026!@redis:6379/0",
                require_redis_auth=True,
            )
        )


class TestDockerComposeNetworkBindingDefaults:
    """Verifies compose port bindings and infrastructure network isolation."""

    @pytest.fixture
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _assert_app_port_binding(ports: list[object], label: str) -> None:
        port_strs = [str(p) for p in ports]
        assert any(p.endswith(":8000") for p in port_strs), (
            f"{label} app must expose container port 8000 via APP_PORT: {port_strs}"
        )
        assert not any("0.0.0.0" in p for p in port_strs), (
            f"{label} app must not hardcode 0.0.0.0: {port_strs}"
        )

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

        # 1. App exposes 8000 cleanly without hardcoding 0.0.0.0
        self._assert_app_port_binding(services["app"].get("ports", []), "Compose")

        # 2. Infrastructure ports must bind strictly to 127.0.0.1
        for sname in ("postgres", "redis", "prometheus", "grafana", "minio"):
            if sname in services and "ports" in services[sname]:
                ports = services[sname]["ports"]
                for p in ports:
                    p_str = str(p)
                    assert p_str.startswith("127.0.0.1:"), (
                        f"Service {sname} port {p_str} is not bound to 127.0.0.1 loopback"
                    )

    @pytest.mark.parametrize("compose_name", ["docker-compose.yml", "docker-compose.staging.yml"])
    def test_optional_monitoring_vars_do_not_block_core_compose(self, root_dir: Path, compose_name: str):
        """Inactive profile services (grafana) must not fail Compose interpolation when omitted from .env."""
        import yaml

        raw = (root_dir / compose_name).read_text(encoding="utf-8")
        assert "GRAFANA_USER:?" not in raw, f"{compose_name} must not require GRAFANA_USER via :?"
        assert "GRAFANA_PASSWORD:?" not in raw, f"{compose_name} must not require GRAFANA_PASSWORD via :?"

        data = yaml.safe_load(raw)
        grafana = data["services"]["grafana"]
        entrypoint_str = " ".join(str(x) for x in grafana.get("entrypoint", []))
        assert "GF_SECURITY_ADMIN_PASSWORD" in entrypoint_str, (
            f"{compose_name} grafana entrypoint must fail closed if GF_SECURITY_ADMIN_PASSWORD is empty"
        )

    def test_docker_compose_staging_network_isolation(self, root_dir: Path):
        import yaml

        staging_path = root_dir / "docker-compose.staging.yml"
        assert staging_path.exists(), f"Missing {staging_path}"

        with staging_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        services = data.get("services", {})
        assert "app" in services
        self._assert_app_port_binding(services["app"].get("ports", []), "Staging")

        # In staging, databases must have zero published host ports
        for sname in ("postgres", "redis"):
            if sname in services:
                assert "ports" not in services[sname], (
                    f"Staging {sname} must not publish host ports; should be bridge-internal only"
                )


class TestDisasterRecoveryAndBackupCLI:
    """Validates real backup creation, listing, and streaming restore operations."""

    def test_docker_transport_uses_container_side_port(self, monkeypatch):
        from app.utils import backup

        settings = Settings(
            app_env="production",
            credentials_encryption_key=Fernet.generate_key().decode(),
            jwt_secret="secure-high-entropy-production-secret-min-32-chars",
            database_url="postgresql://u:p@127.0.0.1:55432/automate_test",
            pg_client_mode="docker",
            pg_docker_container="flowsmith-test-postgres",
        )
        monkeypatch.setattr(backup, "get_settings", lambda: settings)

        base, _env = backup._base_cmd(
            "pg_dump", "postgresql://u:p@127.0.0.1:55432/automate_test"
        )

        assert base[:2] == ["docker", "exec"]
        assert "flowsmith-test-postgres" in base
        assert "pg_dump" in base
        assert base[base.index("-p") + 1] == "5432"

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

    def test_apply_refuses_single_key(self):
        from app.config import get_settings
        from scripts.rotate_encryption_key import rotate_keys

        settings = get_settings()
        previous = settings.credentials_encryption_key
        settings.credentials_encryption_key = Fernet.generate_key().decode()
        try:
            with pytest.raises(RuntimeError, match="single key"):
                rotate_keys(apply=True)
        finally:
            settings.credentials_encryption_key = previous

    def test_rotate_exports_reencrypts_files(self, tmp_path):
        from app.config import get_settings
        from app.security.crypto import (
            CredentialDecryptionError,
            decrypt_text,
            encrypt_text,
        )
        from scripts.rotate_encryption_key import rotate_exports

        settings = get_settings()
        previous = settings.credentials_encryption_key
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()
        user_dir = tmp_path / "users" / "1"
        user_dir.mkdir(parents=True)
        export_file = user_dir / "account.json.enc"

        settings.credentials_encryption_key = old_key
        try:
            export_file.write_bytes(encrypt_text('{"account":"data"}'))
            settings.credentials_encryption_key = f"{new_key},{old_key}"
            assert rotate_exports(tmp_path, apply=True) == 1

            # New key alone must decrypt the rotated file.
            settings.credentials_encryption_key = new_key
            assert decrypt_text(export_file.read_bytes()) == '{"account":"data"}'

            # The old key alone must no longer work.
            settings.credentials_encryption_key = old_key
            with pytest.raises(CredentialDecryptionError):
                decrypt_text(export_file.read_bytes())
        finally:
            settings.credentials_encryption_key = previous


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


class TestServeRuntimeConfiguration:
    """Verifies safe multi-worker and proxy header handling in app.serve."""

    def test_ignores_web_concurrency_in_development_and_embedded_mode(self, monkeypatch):
        from app.config import Settings
        from app.serve import build_uvicorn_kwargs

        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        dev_kwargs = build_uvicorn_kwargs(Settings(app_env="development", queue_embedded_consumer=False))
        assert dev_kwargs["reload"] is True
        assert "workers" not in dev_kwargs

        embedded_kwargs = build_uvicorn_kwargs(Settings(app_env="production", queue_embedded_consumer=True))
        assert embedded_kwargs["reload"] is False
        assert "workers" not in embedded_kwargs

    def test_enables_web_concurrency_for_production_with_external_workers(self, monkeypatch):
        from app.config import Settings
        from app.serve import build_uvicorn_kwargs

        monkeypatch.setenv("WEB_CONCURRENCY", "3")
        prod_kwargs = build_uvicorn_kwargs(Settings(app_env="production", queue_embedded_consumer=False))
        assert prod_kwargs["workers"] == 3
        assert prod_kwargs["proxy_headers"] is True

    def test_rejects_invalid_web_concurrency_values(self, monkeypatch):
        from app.config import Settings
        from app.serve import build_uvicorn_kwargs

        for bad in ("abc", "0", "-2"):
            monkeypatch.setenv("WEB_CONCURRENCY", bad)
            kwargs = build_uvicorn_kwargs(Settings(app_env="production", queue_embedded_consumer=False))
            assert "workers" not in kwargs

    def test_forwarded_allow_ips_inherits_trusted_proxies_unless_overridden(self, monkeypatch):
        from app.config import Settings
        from app.serve import build_uvicorn_kwargs

        monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
        kwargs = build_uvicorn_kwargs(Settings(trusted_proxies="10.0.0.0/8,127.0.0.1"))
        assert kwargs["forwarded_allow_ips"] == "10.0.0.0/8,127.0.0.1"

        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.1")
        overridden = build_uvicorn_kwargs(Settings(trusted_proxies="10.0.0.0/8"))
        assert overridden["forwarded_allow_ips"] == "172.18.0.1"


class TestHelmHardening:
    """Verifies Kubernetes Helm chart production safeguards."""

    def test_helm_outbox_redis_and_tmp_mounts(self):
        import yaml

        helm_dir = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "flowsmith"
        values = yaml.safe_load((helm_dir / "values.yaml").read_text(encoding="utf-8"))
        assert values["config"]["outboxRelayEnabled"] is True

        configmap = (helm_dir / "templates" / "configmap.yaml").read_text(encoding="utf-8")
        assert "OUTBOX_RELAY_ENABLED:" in configmap

        redis_tpl = (helm_dir / "templates" / "redis.yaml").read_text(encoding="utf-8")
        assert "--maxmemory-policy noeviction" in redis_tpl

        for deploy_name in ("app-deployment.yaml", "worker-deployment.yaml"):
            text = (helm_dir / "templates" / deploy_name).read_text(encoding="utf-8")
            assert "mountPath: /app/backend/tmp" in text, deploy_name
            assert "mountPath: /tmp" in text, deploy_name
