"""LDAP authentication fallback, JIT linking, and group-role mapping tests."""

from __future__ import annotations

import pytest

from app.api import auth as auth_api
from app.config import get_settings
from app.services.ldap_auth import (
    LdapProfile,
    LdapUnavailable,
    _server_url,
    build_group_filter,
    build_user_filter,
    parse_group_role_map,
    role_for_groups,
)
from tests.test_api.conftest import register

PASSWORD = "Password123!"


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    auth_api.login_throttle.reset()
    yield
    auth_api.login_throttle.reset()


@pytest.fixture
def ldap_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ldap_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ldap_default_role", "member", raising=False)
    monkeypatch.setattr(settings, "ldap_jit_provisioning", True, raising=False)
    monkeypatch.setattr(settings, "ldap_group_role_map", "", raising=False)
    monkeypatch.setattr(settings, "ldap_user_search_filter", "(uid={username})", raising=False)
    monkeypatch.setattr(settings, "ldap_group_search_filter", "(member={user_dn})", raising=False)
    return settings


def _profile(
    email: str = "ldap-user@example.com",
    groups: tuple[str, ...] = (),
) -> LdapProfile:
    return LdapProfile(
        username="ldapuser",
        email=email,
        dn="uid=ldapuser,ou=people,dc=example,dc=com",
        display_name="LDAP User",
        groups=groups,
    )


def _login(client, identifier: str, password: str = "LdapPassword1!"):
    return client.post(
        "/api/auth/login",
        json={"email": identifier, "password": password},
    )


def test_ldap_fallback_provisions_user_and_maps_admin_group(client, ldap_settings, monkeypatch):
    register(client, "local-admin@example.com", PASSWORD)
    ldap_settings.ldap_group_role_map = '{"platform-admins": "admin"}'
    monkeypatch.setattr(
        auth_api,
        "authenticate_ldap",
        lambda username, password: _profile(groups=("Platform-Admins",)),
    )

    response = _login(client, "ldapuser")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["user"]["email"] == "ldap-user@example.com"
    assert data["user"]["role"] == "admin"
    assert data["token"]

    from app.db import get_session
    from app.models import User

    db = get_session()
    try:
        user = db.query(User).filter(User.email == "ldap-user@example.com").one()
        assert user.role == "admin"
        assert user.active is True
        assert user.password_hash  # random local password, never the LDAP one
        assert "LdapPassword1!" not in user.password_hash
    finally:
        db.close()


def test_ldap_links_existing_account_without_changing_password(client, ldap_settings, monkeypatch):
    register(client, "existing@example.com", PASSWORD)
    monkeypatch.setattr(
        auth_api,
        "authenticate_ldap",
        lambda username, password: _profile(email="existing@example.com", groups=("People",)),
    )

    response = _login(client, "existing", "DirectoryPassword1!")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["user"]["email"] == "existing@example.com"

    # The local password remains valid and LDAP was only a fallback.
    local = _login(client, "existing@example.com", PASSWORD)
    assert local.status_code == 200


def test_ldap_jit_disabled_rejects_unknown_user(client, ldap_settings, monkeypatch):
    register(client, "jit-gate@example.com", PASSWORD)
    ldap_settings.ldap_jit_provisioning = False
    monkeypatch.setattr(
        auth_api,
        "authenticate_ldap",
        lambda username, password: _profile(email="no-jit@example.com"),
    )

    response = _login(client, "nojit")
    assert response.status_code == 401

    from app.db import get_session
    from app.models import User

    db = get_session()
    try:
        assert db.query(User).filter(User.email == "no-jit@example.com").first() is None
    finally:
        db.close()


def test_ldap_cannot_reactivate_deactivated_account(client, ldap_settings, monkeypatch):
    data = register(client, "disabled-ldap@example.com", PASSWORD)
    monkeypatch.setattr(
        auth_api,
        "authenticate_ldap",
        lambda username, password: _profile(email="disabled-ldap@example.com"),
    )

    from app.db import get_session
    from app.models import User

    db = get_session()
    try:
        user = db.get(User, data["user"]["id"])
        assert user is not None
        user.active = False
        db.commit()
    finally:
        db.close()

    assert _login(client, "disabled-ldap", "DirectoryPassword1!").status_code == 401


def test_ldap_outage_fails_closed(client, ldap_settings, monkeypatch):
    register(client, "outage@example.com", PASSWORD)

    def unavailable(username, password):
        raise LdapUnavailable("directory unreachable")

    monkeypatch.setattr(auth_api, "authenticate_ldap", unavailable)
    assert _login(client, "outage", "DirectoryPassword1!").status_code == 401


def test_local_password_does_not_contact_ldap(client, ldap_settings, monkeypatch):
    register(client, "local-only@example.com", PASSWORD)

    def should_not_run(username, password):
        raise AssertionError("LDAP must not be consulted after a valid local password")

    monkeypatch.setattr(auth_api, "authenticate_ldap", should_not_run)
    response = _login(client, "local-only@example.com", PASSWORD)
    assert response.status_code == 200


def test_ldap_filter_escaping_and_role_mapping(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ldap_user_search_filter", "(uid={username})", raising=False)
    assert build_user_filter("a*)(uid=*") == "(uid=a\\2a\\29\\28uid=\\2a)"
    assert "%s" not in build_user_filter("50%")

    monkeypatch.setattr(settings, "ldap_group_search_filter", "(member={user_dn})", raising=False)
    assert build_group_filter("cn=a*") == "(member=cn=a\\2a)"

    roles = parse_group_role_map('{"Platform-Admins":"ADMIN","People":"member","Ignore":"owner"}')
    assert roles == {"platform-admins": "admin", "people": "member"}
    assert role_for_groups(("People",), roles, "member") == "member"
    assert role_for_groups(("platform-admins", "People"), roles, "member") == "admin"
    assert role_for_groups((), roles, "admin") == "admin"


def test_ldap_server_url_parsing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ldap_server_url", "ldaps://ldap.example.com", raising=False)
    assert _server_url(settings.ldap_server_url) == ("ldap.example.com", 636, True)
    monkeypatch.setattr(settings, "ldap_server_url", "ldap://ldap.example.com:1389", raising=False)
    assert _server_url(settings.ldap_server_url) == ("ldap.example.com", 1389, False)
