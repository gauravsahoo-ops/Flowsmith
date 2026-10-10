"""Unit tests for error classification and secret redaction."""

from app.services.error_classification import (
    classify_error,
    compute_fingerprint,
    sanitize_payload,
    sanitize_string,
)


def test_sanitize_string_redacts_tokens():
    raw = "Request failed with header: Bearer ya29.a0AfH6SM... and access_token=secret12345"
    sanitized = sanitize_string(raw)
    assert "ya29.a0AfH6SM" not in sanitized
    assert "secret12345" not in sanitized
    assert "Bearer [REDACTED]" in sanitized
    assert "access_token=[REDACTED]" in sanitized


def test_sanitize_payload_deep_redaction():
    payload = {
        "user": "alice",
        "api_key": "live_key_xyz987",
        "nested": {
            "password": "supersecretpassword",
            "client_secret": "cs_123456",
            "safe_counter": 42,
            "tokens_list": ["Bearer token_abc123", {"refresh_token": "rt_98765"}],
        },
    }
    cleaned = sanitize_payload(payload)
    assert cleaned["user"] == "alice"
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["password"] == "[REDACTED]"
    assert cleaned["nested"]["client_secret"] == "[REDACTED]"
    assert cleaned["nested"]["safe_counter"] == 42
    assert "token_abc123" not in str(cleaned)
    assert cleaned["nested"]["tokens_list"][1]["refresh_token"] == "[REDACTED]"


def test_classify_oauth_session_expired():
    err = {
        "message": "Token refresh failed 400: {\"error\":\"invalid_grant\",\"error_description\":\"expired access/refresh token\"}",
        "code": "AUTH_ERROR",
        "status_code": 400,
    }
    classification = classify_error(err, workflow_name="Lead Sync", connector_type="salesforce")
    assert classification.category == "AUTH_SESSION_EXPIRED"
    assert classification.code == "OAUTH_SESSION_EXPIRED"
    assert classification.severity == "CRITICAL"
    assert "Salesforce" in classification.title
    assert "reconnect" in classification.resolution.lower()


def test_classify_rate_limit():
    err = {"message": "Rate limit exceeded. Try again in 60s.", "status_code": 429}
    classification = classify_error(err, connector_type="dynamics_crm")
    assert classification.category == "CONNECTOR_RATE_LIMIT"
    assert classification.code == "API_RATE_LIMIT_EXCEEDED"
    assert classification.severity == "WARNING"
    assert "Dynamics Crm" in classification.title


def test_classify_service_timeout():
    err = {"message": "Connection to API timed out after 30000ms", "status_code": 504}
    classification = classify_error(err, connector_type="hubspot")
    assert classification.category == "WORKFLOW_TIMEOUT"
    assert classification.code == "HTTP_TIMEOUT"


def test_classify_schema_validation():
    err = {"message": "Missing required variable 'company_id' for node Create Record"}
    classification = classify_error(err, node_name="Create Record")
    assert classification.category == "SCHEMA_VALIDATION_ERROR"
    assert classification.code == "INVALID_DATA_SCHEMA"
    assert "Create Record" in classification.title


def test_compute_fingerprint_deterministic():
    fp1 = compute_fingerprint("AUTH_SESSION_EXPIRED", "OAUTH_SESSION_EXPIRED", 1, "wf-1", "node-1", "salesforce")
    fp2 = compute_fingerprint("AUTH_SESSION_EXPIRED", "OAUTH_SESSION_EXPIRED", 1, "wf-1", "node-1", "salesforce")
    fp3 = compute_fingerprint("AUTH_SESSION_EXPIRED", "OAUTH_SESSION_EXPIRED", 2, "wf-1", "node-1", "salesforce")

    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 32
