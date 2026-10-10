"""API tests for error notifications and preference endpoints."""

from tests.test_api.conftest import auth_headers, register
from app.services.error_monitoring import ErrorMonitoringService


def test_notifications_api_lifecycle(client):
    user_data = register(client, email="notif_user@example.com")
    token = user_data["token"]
    user_id = user_data["user"]["id"]
    headers = auth_headers(token)

    # 1. Initially 0 notifications
    resp = client.get("/api/notifications", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 0

    # 2. Trigger an error event
    ev = ErrorMonitoringService.capture_error(
        db=None,
        error_data={"message": "Failed Salesforce Lead sync: 401 unauthorized", "status_code": 401},
        user_id=user_id,
        connector_type="salesforce",
        workflow_id="wf_sf_lead",
    )
    assert ev is not None

    # 3. Check notifications list
    resp = client.get("/api/notifications", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == ev.id
    assert items[0]["category"] == "AUTH_SESSION_EXPIRED"
    assert items[0]["status"] in ("NOTIFICATION_PENDING", "NOTIFIED")

    # 4. Check stats endpoint
    resp = client.get("/api/notifications/stats", headers=headers)
    assert resp.status_code == 200
    stats = resp.json()["data"]
    assert stats["unresolved_count"] == 1
    assert stats["critical_count"] == 1

    # 5. Get detail
    resp = client.get(f"/api/notifications/{ev.id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()["data"]
    assert detail["id"] == ev.id
    assert "technical_details" in detail

    # 6. Acknowledge
    resp = client.post(f"/api/notifications/{ev.id}/acknowledge", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ACKNOWLEDGED"

    # 7. Resolve
    resp = client.post(f"/api/notifications/{ev.id}/resolve", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "RESOLVED"

    # 8. Check preferences
    resp = client.get("/api/notifications/preferences", headers=headers)
    assert resp.status_code == 200
    prefs = resp.json()["data"]
    assert prefs["email_enabled"] is True

    # 9. Update preferences
    resp = client.put(
        "/api/notifications/preferences",
        json={"email_enabled": False, "cooldown_minutes": 30, "custom_email": "alerts@mycorp.com"},
        headers=headers,
    )
    assert resp.status_code == 200
    upd = resp.json()["data"]
    assert upd["email_enabled"] is False
    assert upd["cooldown_minutes"] == 30
    assert upd["custom_email"] == "alerts@mycorp.com"

    # 10. Send test email
    resp = client.post("/api/notifications/test-email", headers=headers)
    assert resp.status_code == 200
    test_res = resp.json()["data"]
    assert test_res["success"] is True
    assert test_res["target_email"] == "alerts@mycorp.com"


def test_notifications_user_isolation(client):
    user_a = register(client, email="user_a@example.com")
    user_b = register(client, email="user_b@example.com")

    # Create error for user A
    ev_a = ErrorMonitoringService.capture_error(
        db=None,
        error_data={"message": "Private error for A"},
        user_id=user_a["user"]["id"],
    )

    # User B lists notifications -> empty
    resp = client.get("/api/notifications", headers=auth_headers(user_b["token"]))
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0

    # User B tries to view User A's error -> 403 Forbidden
    resp = client.get(f"/api/notifications/{ev_a.id}", headers=auth_headers(user_b["token"]))
    assert resp.status_code == 403
