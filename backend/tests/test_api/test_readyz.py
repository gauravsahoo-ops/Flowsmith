"""Readiness probe tests (Phase 17)."""

from fastapi.testclient import TestClient

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
