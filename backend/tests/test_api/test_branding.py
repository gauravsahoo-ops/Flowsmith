"""Tests for per-user branding and white-labeling."""

from tests.test_api.conftest import auth_headers, move_user_to_org, register


def test_get_branding_public_default(client):
    resp = client.get("/api/branding")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["app_name"] == "Flowsmith"
    assert "primary_color" in data


def test_update_branding_is_user_scoped(client):
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

    me = client.get("/api/branding/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["documentation_url"] == "https://docs.acme.corp"

    # The public pre-login branding stays platform-default.
    public = client.get("/api/branding")
    assert public.json()["data"]["documentation_url"] is None
    assert public.json()["data"]["custom_css"] is None


def test_reset_branding_authenticated(client):
    user_data = register(client)
    headers = auth_headers(user_data["token"])

    client.put("/api/branding", json={
        "app_name": "Custom Name",
        "custom_css": ".custom { color: red; }",
    }, headers=headers)

    resp = client.post("/api/branding/reset", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["app_name"] == "Flowsmith"
    assert data["primary_color"] == "#10b981"
    assert data["logo_data"] is None
    assert data["custom_css"] is None
    assert data["documentation_url"] is None


def test_new_user_does_not_see_another_users_branding(client):
    first = register(client, "brand-owner@example.com", "Password123!")
    second = register(client, "brand-new@example.com", "Password123!")

    resp = client.put(
        "/api/branding",
        json={"app_name": "Owner Brand", "primary_color": "#10b981"},
        headers=auth_headers(first["token"]),
    )
    assert resp.status_code == 200, resp.text

    other = client.get("/api/branding/me", headers=auth_headers(second["token"]))
    assert other.status_code == 200
    assert other.json()["data"]["app_name"] == "Flowsmith"
    assert other.json()["data"]["primary_color"] == "#10b981"


def test_branding_is_private_even_inside_the_same_organization(client):
    first = register(client, "brand-org-owner@example.com", "Password123!")
    second = register(client, "brand-org-member@example.com", "Password123!")
    move_user_to_org(
        second["user"]["id"], f"org_personal_{first['user']['id']}", role="member"
    )

    resp = client.put(
        "/api/branding",
        json={"app_name": "First Account Brand", "primary_color": "#f59e0b"},
        headers=auth_headers(first["token"]),
    )
    assert resp.status_code == 200, resp.text

    first_brand = client.get("/api/branding/me", headers=auth_headers(first["token"]))
    second_brand = client.get("/api/branding/me", headers=auth_headers(second["token"]))
    assert first_brand.json()["data"]["app_name"] == "First Account Brand"
    assert second_brand.json()["data"]["app_name"] == "Flowsmith"
    assert second_brand.json()["data"]["primary_color"] == "#10b981"
