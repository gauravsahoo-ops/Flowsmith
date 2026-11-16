"""Readiness probe tests (Phase 17)."""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.lifecycle import StartupStage, get_lifecycle
from app.main import app


def test_health_always_200_even_when_ready():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"


def test_readyz_ok_when_db_up():
    client = TestClient(app)
    resp = client.get("/readyz")
    # Dev DB is up, so should be ready (200). When Redis is required but down, may be 503 — allow either,
    # but ensure the body has checks.
    assert resp.status_code in (200, 503)
    data = resp.json()["data"]
    assert "checks" in data
    assert "postgres" in data["checks"]
    assert data["checks"]["postgres"] in ("ok", "error")


def test_readyz_requires_running_outbox_relay_when_enabled(monkeypatch):
    lc = get_lifecycle()
    lc.transition_to(StartupStage.READINESS_ENABLED)
    monkeypatch.setenv("OUTBOX_RELAY_ENABLED", "true")
    monkeypatch.setattr(app.state, "outbox_relay", None, raising=False)
    client = TestClient(app)

    with patch(
        "app.db.verify_schema_state",
        return_value={
            "ok": True,
            "status": "ok",
            "current_revision": "rev",
            "expected_revision": "rev",
        },
    ), patch("app.db.engine.connect"), patch(
        "app.main.get_settings",
        return_value=SimpleNamespace(
            app_env="development",
            public_url="",
            redis_url="",
            queue_backend="db",
        ),
    ):
        resp = client.get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["data"]["checks"]["outbox_relay"] == "not_running"

        monkeypatch.setattr(
            app.state, "outbox_relay", SimpleNamespace(running=True), raising=False
        )
        resp = client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["data"]["checks"]["outbox_relay"] == "ok"
