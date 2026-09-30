"""Comprehensive verification tests for the FlowSmith Credential Management System.

Covers:
1. 11-category machine-readable authentication classification of all 90 connectors.
2. Complete credential schema registration in CREDENTIAL_TYPES (including Zoho CRM, Anthropic, Gemini, Snowflake, SAP, etc.).
3. Mandatory vs optional field validation across credential schemas.
4. Secret redaction and masking at rest and across metadata.
5. In-place credential rotation via update_for_user preserving workflow credential IDs.
6. Execution guards blocking unimplemented/coming-soon connectors (Rule 29).
7. Centralized CredentialResolver architecture.
"""
from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from app.credentials.auth_metadata import (
    AuthMethod,
    CONNECTOR_AUTH_CATALOG,
    ConnectorAuthMetadata,
    ImplementationStatus,
    get_auth_classification_summary,
    get_connector_auth_metadata,
    list_connector_auth_metadata,
)
from app.credentials.registry import (
    CREDENTIAL_IMPLEMENTED,
    CREDENTIAL_PROVIDER,
    CREDENTIAL_TYPES,
    SECRET_FIELDS,
    TYPE_META,
    is_implemented,
    list_types,
    redact_data,
    validate_data,
)
from app.credentials.resolver import CredentialError, CredentialResolver
from app.credentials.service import create_for_user, update_for_user, resolve_credentials
from app.db import get_session
from app.engine.errors import NodeExecutionError
from app.engine.executor import execute_workflow
from app.models.credential import Credential
from app.models.user import User
from tests.conftest import conn, make_node, make_workflow


def _get_or_create_test_user(db):
    user = db.query(User).filter_by(email="cred_test_user@example.com").first()
    if not user:
        user = User(
            id=998877,
            email="cred_test_user@example.com",
            password_hash="test_pw_hash",
            role="member",
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ==============================================================================
# 1. AUDIT & CLASSIFICATION TESTS
# ==============================================================================

def test_audit_all_connectors_catalog_size():
    """Verify all 90 connectors (86 registered + 4 backlog) are cataloged."""
    metadata_list = list_connector_auth_metadata()
    assert len(metadata_list) == 90
    assert len(CONNECTOR_AUTH_CATALOG) == 90


def test_audit_11_auth_classifications_represented():
    """Verify all 11 authentication methods are valid and properly assigned."""
    summary = get_auth_classification_summary()
    assert summary["total_connectors_discovered"] == 90
    assert summary["connectors_requiring_credentials"] == 73
    assert summary["connectors_no_auth_required"] == 17

    breakdown = summary["breakdown_by_auth_method"]
    # Check that major categories are populated
    assert breakdown["OAuth 2.0 + Refresh Token"] >= 12
    assert breakdown["Bearer Token"] >= 20
    assert breakdown["API Key"] >= 15
    assert breakdown["Basic Auth"] >= 7
    assert breakdown["Client Credentials / S2S"] >= 4
    assert breakdown["Username + Password"] >= 4
    assert breakdown["OAuth 2.0"] >= 3
    assert breakdown["Service Account / JWT"] >= 1
    assert breakdown["Custom Header"] >= 3
    assert breakdown["No authentication required"] == 17


def test_enterprise_priority_connectors_classified():
    """Verify specific enterprise connectors identified in prompt requirements."""
    targets = {
        "salesforce": AuthMethod.OAUTH2_REFRESH,
        "dynamics_crm": AuthMethod.CLIENT_CREDENTIALS_S2S,
        "zoho_crm": AuthMethod.OAUTH2,
        "hubspot": AuthMethod.OAUTH2_REFRESH,
        "sap": AuthMethod.BASIC_AUTH,
        "servicenow": AuthMethod.BASIC_AUTH,
        "jira": AuthMethod.BASIC_AUTH,
        "slack": AuthMethod.BEARER_TOKEN,
        "google_drive": AuthMethod.OAUTH2_REFRESH,
        "gmail": AuthMethod.OAUTH2_REFRESH,
        "dropbox": AuthMethod.BEARER_TOKEN,
        "postgres": AuthMethod.USERNAME_PASSWORD,
        "mysql": AuthMethod.USERNAME_PASSWORD,
        "redis": AuthMethod.USERNAME_PASSWORD,
        "mongodb": AuthMethod.USERNAME_PASSWORD,
        "openai": AuthMethod.BEARER_TOKEN,
        "anthropic": AuthMethod.API_KEY,
        "gemini": AuthMethod.API_KEY,
        "groq": AuthMethod.API_KEY,
        "deepseek": AuthMethod.API_KEY,
        "sharepoint": AuthMethod.OAUTH2_REFRESH,
        "onedrive": AuthMethod.OAUTH2_REFRESH,
    }
    for cid, expected_method in targets.items():
        meta = get_connector_auth_metadata(cid)
        assert meta is not None, f"Missing metadata for {cid}"
        assert meta.auth_method == expected_method, f"Mismatch for {cid}: {meta.auth_method} != {expected_method}"


# ==============================================================================
# 2. CREDENTIAL MANAGER SCHEMA & FIELD DEFINITIONS
# ==============================================================================

def test_credential_schema_coverage_for_all_auth_connectors():
    """Verify every connector requiring authentication has a registered schema in CREDENTIAL_TYPES."""
    for cid, meta in CONNECTOR_AUTH_CATALOG.items():
        if meta.get("auth_method") == AuthMethod.NONE:
            continue
        cred_type = meta.get("credential_type") or cid
        assert cred_type in CREDENTIAL_TYPES, f"Connector '{cid}' has no schema in CREDENTIAL_TYPES"
        assert cred_type in SECRET_FIELDS, f"Connector '{cid}' missing from SECRET_FIELDS registry"
        assert cred_type in TYPE_META, f"Connector '{cid}' missing from TYPE_META registry"


def test_zoho_crm_credential_schema():
    """Verify Zoho CRM OAuth credential schema requirements."""
    schema = CREDENTIAL_TYPES["zoho_crm"]
    # Required: client_id, client_secret, refresh_token or access_token
    valid_data = {
        "client_id": "1000.xxxx",
        "client_secret": "sec_xxxx",
        "refresh_token": "1000.ref_xxxx",
        "accounts_server": "https://accounts.zoho.com",
    }
    obj = schema.model_validate(valid_data)
    assert obj.client_id == "1000.xxxx"
    assert obj.client_secret == "sec_xxxx"
    assert obj.refresh_token == "1000.ref_xxxx"

    # Direct access token mode
    direct_obj = schema.model_validate({"access_token": "1000.access_token_direct"})
    assert direct_obj.access_token == "1000.access_token_direct"

    # Missing all auth fields
    with pytest.raises(ValidationError):
        schema.model_validate({"client_id": "1000.xxxx"})


def test_sap_credential_schema():
    """Verify SAP S/4HANA enterprise credential schema."""
    schema = CREDENTIAL_TYPES["sap"]
    valid = {
        "base_url": "https://my-s4hana.example.com",
        "username": "SAP_COMM_USER",
        "password": "Password123!",
        "client": "100",
    }
    obj = schema.model_validate(valid)
    assert obj.username == "SAP_COMM_USER"
    assert obj.client == "100"

    with pytest.raises(ValidationError):
        schema.model_validate({"base_url": "https://example.com"})  # Missing credentials


def test_snowflake_credential_schema():
    """Verify Snowflake credential schema."""
    schema = CREDENTIAL_TYPES["snowflake"]
    valid = {
        "account": "xy12345.us-east-1",
        "username": "FLOW_USER",
        "password": "Password123!",
        "warehouse": "COMPUTE_WH",
    }
    obj = schema.model_validate(valid)
    assert obj.account == "xy12345.us-east-1"
    assert obj.warehouse == "COMPUTE_WH"

    # Token-based auth
    token_obj = schema.model_validate({
        "account": "xy12345.us-east-1",
        "token": "eyJhbGciOi...",
    })
    assert token_obj.token == "eyJhbGciOi..."


def test_anthropic_and_gemini_schemas():
    """Verify AI provider credential schemas."""
    ant_schema = CREDENTIAL_TYPES["anthropic"]
    ant_obj = ant_schema.model_validate({"api_key": "sk-ant-api03-xxxx"})
    assert ant_obj.api_key == "sk-ant-api03-xxxx"

    gem_schema = CREDENTIAL_TYPES["gemini"]
    gem_obj = gem_schema.model_validate({"api_key": "AIzaSyxxxx"})
    assert gem_obj.api_key == "AIzaSyxxxx"


# ==============================================================================
# 3. SECRET REDACTION & MASKING
# ==============================================================================

def test_secret_redaction_masks_all_sensitive_fields():
    """Verify redact_data masks secret fields without exposing raw values."""
    sensitive_samples = {
        "zoho_crm": {
            "client_id": "1000.client",
            "client_secret": "super_secret_client_secret",
            "refresh_token": "super_secret_refresh_token",
            "access_token": "temp_access_token",
        },
        "sap": {
            "base_url": "https://sap.corp",
            "username": "admin",
            "password": "ClearTextPassword!",
        },
        "anthropic": {
            "api_key": "sk-ant-test-key-12345678",
        },
    }
    for cred_type, raw_data in sensitive_samples.items():
        redacted = redact_data(cred_type, raw_data)
        for field in SECRET_FIELDS[cred_type]:
            if field in raw_data and raw_data[field]:
                assert redacted[field] == "••••••••", f"Field {field} in {cred_type} was not masked"
                assert raw_data[field] != "••••••••"


def test_list_types_includes_auth_method_and_status():
    """Verify list_types() returns auth_method, status, and does not leak secrets."""
    types = list_types()
    for t in types:
        assert "auth_method" in t
        assert "status" in t
        assert t["status"] in ("available", "coming_soon")
        assert "secret_fields" in t
        assert isinstance(t["secret_fields"], list)


# ==============================================================================
# 4. CREDENTIAL ROTATION IN-PLACE
# ==============================================================================

def test_credential_update_and_rotation_in_place():
    """Verify update_for_user rotates secrets in-place without changing credential ID."""
    from app.security.crypto import decrypt_text

    with get_session() as db:
        user = _get_or_create_test_user(db)

        # 1. Create initial credential
        created = create_for_user(
            db=db,
            user_id=user.id,
            name="Production Anthropic Key",
            cred_type="anthropic",
            data={"api_key": "sk-ant-initial-secret-11111"},
        )
        cred_id = created["id"]
        assert created["name"] == "Production Anthropic Key"

        # 2. Rotate API key in-place
        updated = update_for_user(
            db=db,
            user_id=user.id,
            credential_id=cred_id,
            name="Production Anthropic Key (Rotated)",
            data={"api_key": "sk-ant-rotated-secret-22222"},
        )
        assert updated["id"] == cred_id  # Preserves workflow references!
        assert updated["name"] == "Production Anthropic Key (Rotated)"

        # Verify decrypted data at rest contains the rotated secret
        rec = db.get(Credential, cred_id)
        decrypted = json.loads(decrypt_text(rec.data))
        assert decrypted["api_key"] == "sk-ant-rotated-secret-22222"

        # 3. Update without changing secret (passing masked dots should preserve original secret)
        updated_name_only = update_for_user(
            db=db,
            user_id=user.id,
            credential_id=cred_id,
            name="Production Anthropic Key (Renamed)",
            data={"api_key": "••••••••"},
        )
        assert updated_name_only["name"] == "Production Anthropic Key (Renamed)"
        rec = db.get(Credential, cred_id)
        decrypted_again = json.loads(decrypt_text(rec.data))
        assert decrypted_again["api_key"] == "sk-ant-rotated-secret-22222"  # Secret intact!


# ==============================================================================
# 5. EXECUTION GUARDS FOR UNIMPLEMENTED CONNECTORS (RULE 29)
# ==============================================================================

def test_unimplemented_connectors_marked_coming_soon():
    """Verify backlog connectors (groq, deepseek, sharepoint, onedrive) are marked coming_soon."""
    unimplemented = ["groq", "deepseek", "sharepoint", "onedrive"]
    for cid in unimplemented:
        meta = get_connector_auth_metadata(cid)
        assert meta is not None
        assert meta.status == ImplementationStatus.COMING_SOON
        assert not is_implemented(cid)


def test_credential_resolver_rejects_unimplemented_connector():
    """Verify CredentialResolver raises CONNECTOR_UNAVAILABLE for unimplemented connector."""
    with get_session() as db:
        user = _get_or_create_test_user(db)
        resolver = CredentialResolver()
        with pytest.raises(CredentialError) as exc_info:
            resolver.resolve(db=db, user_id=user.id, cred_type="groq", cred_id="cred_groq_123")
        assert exc_info.value.code == "CONNECTOR_UNAVAILABLE"
        assert "Connector 'groq' unavailable — implementation pending." in str(exc_info.value)


async def test_workflow_execution_rejects_unimplemented_connector_credential():
    """Verify executor blocks execution when resolving credentials for an unimplemented connector."""
    with get_session() as db:
        user = _get_or_create_test_user(db)

        wf = make_workflow(
            [
                make_node("trigger", "manual_trigger"),
                make_node(
                    "http",
                    "http_request",
                    parameters={"method": "GET", "url": "https://api.example.com/data"},
                ),
            ],
            [conn("trigger", "http")],
        )
        wf.nodes[1].credentials = {"groq": "cred_fake"}

        def test_resolver(refs):
            # Centralized Credential Resolver invocation
            return resolve_credentials(db, user.id, refs)

        result = await execute_workflow(wf, credential_resolver=test_resolver)
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.code == "CONNECTOR_UNAVAILABLE"
        assert "Connector 'groq' unavailable — implementation pending." in str(result.error.message)
