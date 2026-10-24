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
        "public_url": "https://app.example.com",
        "cors_origins": "https://app.example.com",
        "registration_bootstrap_token": "bootstrap-token-with-at-least-32-characters",
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


def test_production_saml_requires_idp_metadata() -> None:
    with pytest.raises(ConfigError, match="SAML_IDP_METADATA"):
        validate_production_settings(_settings(saml_enabled=True))


def test_production_saml_metadata_url_must_be_https() -> None:
    with pytest.raises(ConfigError, match="SAML_IDP_METADATA_URL"):
        validate_production_settings(_settings(
            saml_enabled=True,
            saml_idp_metadata_url="http://idp.example.com/metadata",
        ))


def test_production_saml_requires_private_key_for_sp_certificate() -> None:
    with pytest.raises(ConfigError, match="SAML_SP_PRIVATE_KEY"):
        validate_production_settings(_settings(
            saml_enabled=True,
            saml_idp_metadata_xml="<EntityDescriptor/>",
            saml_sp_x509_cert="not-a-real-cert",
        ))


def test_production_saml_accepts_inline_metadata() -> None:
    validate_production_settings(_settings(
        saml_enabled=True,
        saml_idp_metadata_xml="<EntityDescriptor/>",
    ))


def test_production_saml_group_role_map_validation() -> None:
    with pytest.raises(ConfigError, match="SAML_GROUP_ROLE_MAP"):
        validate_production_settings(_settings(
            saml_enabled=True,
            saml_idp_metadata_xml="<EntityDescriptor/>",
            saml_group_role_map='{"platform-admins": "owner"}',
        ))
    validate_production_settings(_settings(
        saml_enabled=True,
        saml_idp_metadata_xml="<EntityDescriptor/>",
        saml_group_role_map='{"platform-admins": "admin", "employees": "member"}',
    ))


def test_production_saml_accepts_private_key_for_decryption_only() -> None:
    validate_production_settings(_settings(
        saml_enabled=True,
        saml_idp_metadata_xml="<EntityDescriptor/>",
        saml_sp_private_key="not-parsed-at-config-validation",
    ))


def test_production_webauthn_requires_rp_id_and_https_origin() -> None:
    with pytest.raises(ConfigError, match="WEBAUTHN_RP_ID"):
        validate_production_settings(_settings(webauthn_enabled=True))
    with pytest.raises(ConfigError, match="WEBAUTHN_ORIGIN"):
        validate_production_settings(_settings(
            webauthn_enabled=True,
            webauthn_rp_id="flowsmith.example.com",
            webauthn_origin="http://flowsmith.example.com",
        ))
    with pytest.raises(ConfigError, match="WEBAUTHN_RP_ID"):
        validate_production_settings(_settings(
            webauthn_enabled=True,
            webauthn_rp_id="example.com",
            webauthn_origin="https://flowsmith.example.org",
        ))
    validate_production_settings(_settings(
        webauthn_enabled=True,
        webauthn_rp_id="example.com",
        webauthn_origin="https://flowsmith.example.com",
    ))


def test_production_webauthn_attestation_requires_roots(tmp_path) -> None:
    with pytest.raises(ConfigError, match="WEBAUTHN_ATTESTATION_ROOTS_FILE"):
        validate_production_settings(_settings(
            webauthn_enabled=True,
            webauthn_rp_id="example.com",
            webauthn_origin="https://flowsmith.example.com",
            webauthn_attestation="direct",
        ))
    roots = tmp_path / "roots.pem"
    roots.write_text("-----BEGIN CERTIFICATE-----\nnot-real\n-----END CERTIFICATE-----\n")
    validate_production_settings(_settings(
        webauthn_enabled=True,
        webauthn_rp_id="example.com",
        webauthn_origin="https://flowsmith.example.com",
        webauthn_attestation="direct",
        webauthn_attestation_roots_file=str(roots),
        webauthn_allowed_formats="packed",
        webauthn_allowed_aaguids="11111111-1111-1111-1111-111111111111",
    ))


def test_production_ldap_requires_secure_url_and_search_base() -> None:
    with pytest.raises(ConfigError, match="LDAP_SERVER_URL"):
        validate_production_settings(_settings(ldap_enabled=True))
    with pytest.raises(ConfigError, match="LDAP_SERVER_URL"):
        validate_production_settings(_settings(
            ldap_enabled=True,
            ldap_server_url="ldap://ldap.example.com",
            ldap_start_tls=False,
            ldap_user_search_base="ou=people,dc=example,dc=com",
        ))
    with pytest.raises(ConfigError, match="LDAP_USER_SEARCH_BASE"):
        validate_production_settings(_settings(
            ldap_enabled=True,
            ldap_server_url="ldaps://ldap.example.com",
        ))


def test_production_ldap_requires_valid_filter_and_tls_verification() -> None:
    with pytest.raises(ConfigError, match="LDAP_USER_SEARCH_FILTER"):
        validate_production_settings(_settings(
            ldap_enabled=True,
            ldap_server_url="ldaps://ldap.example.com",
            ldap_user_search_base="ou=people,dc=example,dc=com",
            ldap_user_search_filter="(uid=someone)",
        ))
    with pytest.raises(ConfigError, match="LDAP_TLS_VERIFY"):
        validate_production_settings(_settings(
            ldap_enabled=True,
            ldap_server_url="ldaps://ldap.example.com",
            ldap_tls_verify=False,
            ldap_user_search_base="ou=people,dc=example,dc=com",
        ))


def test_production_ldap_workspace_map_validation() -> None:
    with pytest.raises(ConfigError, match="LDAP_GROUP_WORKSPACE_MAP"):
        validate_production_settings(_settings(
            ldap_enabled=True,
            ldap_server_url="ldaps://ldap.example.com",
            ldap_user_search_base="ou=people,dc=example,dc=com",
            ldap_group_workspace_map='{"employees": [{"workspace_id": "ws_x", "role": "owner"}]}',
        ))
    validate_production_settings(_settings(
        ldap_enabled=True,
        ldap_server_url="ldaps://ldap.example.com",
        ldap_user_search_base="ou=people,dc=example,dc=com",
        ldap_group_workspace_map='{"employees": [{"workspace_id": "ws_x", "permission": "view"}]}',
    ))


def test_production_ldap_org_map_and_sync_validation() -> None:
    with pytest.raises(ConfigError, match="LDAP_GROUP_ORG_MAP"):
        validate_production_settings(_settings(
            ldap_enabled=True,
            ldap_server_url="ldaps://ldap.example.com",
            ldap_user_search_base="ou=people,dc=example,dc=com",
            ldap_group_org_map='{"employees": [{"organization_id": "org_x", "role": "owner"}]}',
        ))
    with pytest.raises(ConfigError, match="LDAP_SYNC_INTERVAL_SECONDS"):
        validate_production_settings(_settings(
            ldap_enabled=True,
            ldap_server_url="ldaps://ldap.example.com",
            ldap_user_search_base="ou=people,dc=example,dc=com",
            ldap_sync_interval_seconds=10,
        ))
    validate_production_settings(_settings(
        ldap_enabled=True,
        ldap_server_url="ldaps://ldap.example.com",
        ldap_user_search_base="ou=people,dc=example,dc=com",
        ldap_group_org_map='{"employees": [{"organization_id": "org_x", "permission": "edit"}]}',
        ldap_sync_enabled=True,
        ldap_sync_interval_seconds=900,
    ))


def test_production_ldap_accepts_secure_configuration() -> None:
    validate_production_settings(_settings(
        ldap_enabled=True,
        ldap_server_url="ldaps://ldap.example.com",
        ldap_user_search_base="ou=people,dc=example,dc=com",
        ldap_group_search_base="ou=groups,dc=example,dc=com",
        ldap_group_role_map='{"platform-admins": "admin"}',
    ))


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
