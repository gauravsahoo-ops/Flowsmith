"""Production config guards (Phase 23 hardening)."""

from __future__ import annotations

import pytest

from app.config import ConfigError, Settings, validate_production_settings


def _settings(**overrides) -> Settings:
    base = {
        "app_env": "production",
        "credentials_encryption_key": "k1:abcdefghijklmnop",
        "jwt_secret": "prod-secret-that-is-long-enough-32-bytes",
        "database_url": "postgresql://u:p@localhost:5432/db",
        "cors_origins": "https://app.example.com",
        # Hermetic: the ambient backend\.env sets a dev SSRF allowlist that
        # would otherwise trip the production bypass gate.
        "safe_http_allowed_hosts": "",
        "safe_http_allowed_ports": "",
    }
    base.update(overrides)
    return Settings(**base)


def test_production_accepts_complete_config() -> None:
    validate_production_settings(_settings())


def test_production_requires_encryption_key() -> None:
    with pytest.raises(ConfigError, match="CREDENTIALS_ENCRYPTION_KEY"):
        validate_production_settings(_settings(credentials_encryption_key=""))


def test_production_requires_real_jwt_secret() -> None:
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        validate_production_settings(_settings(jwt_secret="dev-only-secret-change-me"))
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        validate_production_settings(_settings(jwt_secret=""))


def test_production_requires_postgres() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        validate_production_settings(_settings(database_url="sqlite:///./data/app.db"))


def test_production_allows_unconfigured_optional_connectors() -> None:
    """Salesforce is an optional connector: leaving it unconfigured must
    not block startup."""
    validate_production_settings(
        _settings(salesforce_client_id="", salesforce_client_secret="")
    )


def test_development_skips_all_guards() -> None:
    validate_production_settings(
        Settings(
            app_env="development",
            credentials_encryption_key="",
            jwt_secret="dev-only-secret-change-me",
        )
    )


def test_production_rejects_ssrf_allowlist_without_opt_in() -> None:
    """SAFE_HTTP_ALLOWED_HOSTS / PORTS silently disable the SSRF guard, so
    production refuses them unless ALLOW_SSRF_BYPASS opts in explicitly."""
    with pytest.raises(ConfigError, match="ALLOW_SSRF_BYPASS"):
        validate_production_settings(
            _settings(safe_http_allowed_hosts="127.0.0.1,localhost")
        )
    with pytest.raises(ConfigError, match="ALLOW_SSRF_BYPASS"):
        validate_production_settings(_settings(safe_http_allowed_ports="8181"))


def test_production_allows_ssrf_allowlist_with_explicit_opt_in() -> None:
    validate_production_settings(
        _settings(
            safe_http_allowed_hosts="127.0.0.1,localhost",
            allow_ssrf_bypass="true",
        )
    )
