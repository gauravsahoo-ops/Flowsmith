"""File-based secret loading for Docker/Kubernetes secret mounts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_secret_file_sources_load_scalar_secrets(tmp_path, monkeypatch):
    jwt_file = tmp_path / "jwt_secret"
    jwt_file.write_text("file-jwt-" + "x" * 40 + "\n", encoding="utf-8")
    db_file = tmp_path / "database_url"
    db_file.write_text("postgresql://usr:strongpwd@db:5432/automate\n", encoding="utf-8")
    metrics_file = tmp_path / "metrics_token"
    metrics_file.write_text("metrics-" + "y" * 40, encoding="utf-8")

    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    monkeypatch.setenv("JWT_SECRET_FILE", str(jwt_file))
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_file))
    monkeypatch.setenv("METRICS_TOKEN_FILE", str(metrics_file))

    settings = Settings(_env_file=None)

    assert settings.jwt_secret == "file-jwt-" + "x" * 40
    assert settings.database_url == "postgresql://usr:strongpwd@db:5432/automate"
    assert settings.metrics_token == "metrics-" + "y" * 40


def test_direct_environment_wins_over_secret_file(tmp_path, monkeypatch):
    secret_file = tmp_path / "jwt_secret"
    secret_file.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv("JWT_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("JWT_SECRET", "from-environment")

    settings = Settings(_env_file=None)

    assert settings.jwt_secret == "from-environment"


def test_missing_secret_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("JWT_SECRET_FILE", str(tmp_path / "missing"))

    with pytest.raises((ValueError, ValidationError), match="JWT_SECRET_FILE"):
        Settings(_env_file=None)


def test_arbitrary_file_setting_is_not_loaded(tmp_path, monkeypatch):
    redirect_file = tmp_path / "cors"
    redirect_file.write_text("https://attacker.example", encoding="utf-8")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("CORS_ORIGINS_FILE", str(redirect_file))

    settings = Settings(_env_file=None)

    assert settings.cors_origins == "http://localhost:5173"
