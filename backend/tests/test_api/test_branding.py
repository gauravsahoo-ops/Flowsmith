"""Tests for company branding and white-labeling API."""

from tests.test_api.conftest import auth_headers, register


def test_get_branding_public_default(client):
    resp = client.get("/api/branding")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["app_name"] == "Flowsmith"
    assert "primary_color" in data


def test_update_branding_authenticated(client):
    user_data = register(client)
    headers = auth_headers(user_data["token"])

    payload = {
        "app_name": "Acme Automations",
        "tagline": "Next-Gen Enterprise Engine",
        "primary_color": "#10b981",
        "logo_data": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        "documentation_url": "https://docs.acme.corp",
        "support_email": "ops@acme.corp",
        "copyright_text": "© 2026 Acme Corp. All rights reserved.",
        "custom_css": ":root { --custom-acme: #10b981; }",
    }
    resp = client.put("/api/branding", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["app_name"] == "Acme Automations"
    assert data["tagline"] == "Next-Gen Enterprise Engine"
    assert data["primary_color"] == "#10b981"
    assert data["logo_data"] == "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="
    assert data["documentation_url"] == "https://docs.acme.corp"
    assert data["support_email"] == "ops@acme.corp"
    assert data["copyright_text"] == "© 2026 Acme Corp. All rights reserved."
    assert data["custom_css"] == ":root { --custom-acme: #10b981; }"

    # Verify public GET returns updated branding
    get_resp = client.get("/api/branding")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["documentation_url"] == "https://docs.acme.corp"
    assert get_resp.json()["data"]["custom_css"] == ":root { --custom-acme: #10b981; }"


def test_reset_branding_authenticated(client):
    user_data = register(client)
    headers = auth_headers(user_data["token"])

    # Update first
    client.put("/api/branding", json={
        "app_name": "Custom Name",
        "custom_css": ".custom { color: red; }",
    }, headers=headers)

    # Now reset
    resp = client.post("/api/branding/reset", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["app_name"] == "Flowsmith"
    assert data["primary_color"] == "#6366f1"
    assert data["logo_data"] is None
    assert data["custom_css"] is None
    assert data["documentation_url"] is None
