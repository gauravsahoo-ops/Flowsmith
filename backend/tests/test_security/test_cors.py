"""CORS hardening tests (Phase 16)."""

import pytest

from app.config import ConfigError, Settings, validate_production_settings


def _prod_settings(**overrides):
    base = dict(
        app_env="production",
        credentials_encryption_key="k1:abcdefghijklmnop",
        jwt_secret="prod-secret-that-is-long-enough-32-bytes!!",
        database_url="postgresql://u:p@localhost:5432/db",
        cors_origins="http://localhost:8000",
        # Hermetic: the ambient backend\.env sets a dev SSRF allowlist that
        # would otherwise trip the production bypass gate.
        safe_http_allowed_hosts="",
        safe_http_allowed_ports="",
    )
    base.update(overrides)
    return Settings(**base)


def test_production_rejects_wildcard_cors():
    with pytest.raises(ConfigError, match="CORS_ORIGINS"):
        validate_production_settings(_prod_settings(cors_origins="*"))
    with pytest.raises(ConfigError, match="CORS_ORIGINS"):
        validate_production_settings(_prod_settings(cors_origins="http://a.com, *, http://b.com"))


def test_production_allows_explicit_origins():
    validate_production_settings(_prod_settings(cors_origins="https://app.example.com, https://admin.example.com"))


def test_development_allows_wildcard():
    # Development must still allow "*" for local dev convenience.
    validate_production_settings(Settings(app_env="development", cors_origins="*"))
